"""
Jobs API — read, archive, import, favorite, and dismiss job records.

Contract:
  GET    /api/app/jobs?status=&limit=&offset=&include_report_summary=&favorites_only=&not_interested_only=  → JobList
  GET    /api/app/jobs/{job_id}                → JobRead
  POST   /api/app/jobs/import                  → JobImportResponse
  DELETE /api/app/jobs/{job_id}                → 204 (soft-delete: sets status to "archived")
  POST   /api/app/jobs/{job_id}/favorite       → FavoriteResponse
  DELETE /api/app/jobs/{job_id}/favorite       → FavoriteResponse
  POST   /api/app/jobs/{job_id}/not-interested → NotInterestedResponse
  DELETE /api/app/jobs/{job_id}/not-interested → NotInterestedResponse

Results are always scoped to the authenticated user's workspace.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from apps.api.dependencies.auth import get_current_workspace
from apps.api.dependencies.db import get_db
from packages.contracts.api.jobs import (
    BatchAnalyzeRequest,
    BatchAnalyzeResponse,
    BatchArchiveRequest,
    BatchArchiveResponse,
    FavoriteResponse,
    JDStructured,
    JobImportRequest,
    JobImportResponse,
    JobList,
    JobRead,
    NotInterestedResponse,
)
from packages.infrastructure.db.models import Job, Workspace
from packages.infrastructure.db.repositories import (
    JobApplicationRepository,
    JobFavoriteRepository,
    JobNotInterestedRepository,
    JobRepository,
    JobReportRepository,
    ProfileRepository,
    RunRepository,
    TaskRepository,
)
from packages.infrastructure.services.job_ingest_service import (
    ingest_from_paste,
    ingest_from_url,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/app/jobs", tags=["jobs"])


def _get_celery():
    import os
    from celery import Celery
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    return Celery(broker=redis_url)


def _infer_seniority_from_title(title: str) -> Optional[str]:
    """Heuristic seniority bucket from job title for inbox filtering."""
    t = title.lower()
    if re.search(r"\b(managing director|executive director|c[eo]o|cfo|head of)\b", t):
        return "director"
    if re.search(r"\b(director|svp|senior vice president)\b", t):
        return "director"
    if re.search(r"\b(vp|vice president|principal|lead)\b", t):
        return "lead"
    if re.search(r"\b(svp|senior|sr\.?)\b", t):
        return "senior"
    if re.search(r"\b(avp|manager|mid)\b", t):
        return "mid"
    if re.search(r"\b(analyst|associate|junior|entry)\b", t):
        return "junior"
    return None


def _get_workspace_job(db: Session, workspace: Workspace, job_id: str) -> Job:
    """Fetch a job and verify it belongs to a run in the current workspace."""
    job = JobRepository(db).get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found.")
    if not job.discovered_run_id:
        raise HTTPException(status_code=403, detail="Access denied.")
    run = RunRepository(db).get(job.discovered_run_id)
    if run is None or run.workspace_id != workspace.id:
        raise HTTPException(status_code=403, detail="Access denied.")
    return job


def _job_read(
    job,
    report=None,
    include_jd_structured: bool = False,
    is_favorited: bool = False,
    is_not_interested: bool = False,
    is_applied: bool = False,
) -> JobRead:
    data = {
        "id": job.id,
        "canonical_url": job.canonical_url,
        "source_url": job.source_url,
        "source_type": job.source_type,
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "status": job.status,
        "discovered_run_id": job.discovered_run_id,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "last_seen_at": job.last_seen_at,
        "jd_source": (job.raw_payload_json or {}).get("jd_source"),
        "is_favorited": is_favorited,
        "is_not_interested": is_not_interested,
        "is_applied": is_applied,
    }
    if report:
        data["latest_job_report_id"] = report.id
    if report and report.structured_json:
        s = report.structured_json
        data["primary_role_category"] = s.get("primary_role_category")
        data["role_category_confidence"] = s.get("role_category_confidence")
        pf = s.get("position_function") or {}
        if isinstance(pf, dict) and pf.get("confidence"):
            if not data["role_category_confidence"]:
                data["role_category_confidence"] = pf.get("confidence")
        data["seniority_inferred"] = _infer_seniority_from_title(job.title)
    if include_jd_structured and job.raw_payload_json:
        jd_raw = job.raw_payload_json.get("jd_structured")
        if isinstance(jd_raw, dict) and "_extraction_error" not in jd_raw:
            data["jd_structured"] = JDStructured.model_validate(jd_raw)
    return JobRead.model_validate(data)


@router.get("", response_model=JobList)
def list_jobs(
    status: Optional[str] = Query(None, description="Filter by job status: discovered|reportable|invalid|stale"),
    include_report_summary: bool = Query(
        False,
        description="Join latest active job report for role category/seniority/confidence fields",
    ),
    favorites_only: bool = Query(False, description="Only return jobs bookmarked in this workspace"),
    not_interested_only: bool = Query(False, description="Only return jobs dismissed as not interested in this workspace"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
) -> JobList:
    """List job records discovered in the current workspace."""
    runs = RunRepository(db).list_for_workspace(workspace.id, limit=10_000)
    run_ids = [r.id for r in runs]
    if not run_ids:
        return JobList(items=[], total=0)

    favorited_ids = JobFavoriteRepository(db).list_job_ids_for_workspace(workspace.id)
    not_interested_ids = JobNotInterestedRepository(db).list_job_ids_for_workspace(workspace.id)
    applied_ids = JobApplicationRepository(db).list_job_ids_for_workspace(workspace.id)

    job_ids_filter = None
    if favorites_only and not_interested_only:
        job_ids_filter = favorited_ids & not_interested_ids
    elif favorites_only:
        job_ids_filter = favorited_ids
    elif not_interested_only:
        job_ids_filter = not_interested_ids

    items, total = JobRepository(db).list(
        run_ids=run_ids,
        status=status,
        job_ids=job_ids_filter,
        # Keep paste-created jobs out of the discovery library. They belong to a
        # tracked application, not the job feed; the tracker detail reaches them
        # directly via JobRepository.get, which this filter does not touch. This
        # is the one server-side change the W1 http-assumption audit requires —
        # every Home derivation (topPicks/total/company rollup) reuses this same
        # endpoint, so it is corrected here for free.
        exclude_source_types=["manual_paste"],
        limit=limit,
        offset=offset,
    )

    report_map = {}
    if include_report_summary and items:
        job_ids = [j.id for j in items]
        report_map = JobReportRepository(db).get_latest_active_map(job_ids)

    return JobList(
        items=[
            _job_read(
                j,
                report_map.get(j.id),
                is_favorited=j.id in favorited_ids,
                is_not_interested=j.id in not_interested_ids,
                is_applied=j.id in applied_ids,
            )
            for j in items
        ],
        total=total,
    )


@router.post("/import", response_model=JobImportResponse, status_code=200)
def import_job(
    body: JobImportRequest,
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
) -> JobImportResponse:
    """Import a single job — two feed chutes into one pipeline (job_ingest_service):
    EITHER `url` (fetch + extract) XOR `company`+`title`+`jd_text` (a pasted JD).

    W1 http-assumption audit — the paste path stores a synthetic manual://<ws>/<hash>
    canonical url, so every place that assumes canonical_url is http(s) was checked:
      - view-posting link (frontend): gated on canonical_url.startsWith("http") in the
        tracker detail (P0) AND the /jobs detail + pane (added here) — manual:// renders
        as plain text, never a broken anchor.
      - list_jobs / discovery library: filtered here via exclude_source_types=["manual_paste"];
        Home's topPicks/total/company counts reuse that same endpoint → covered for free.
      - fetch_jd_from_url / re-fetch / reconciliation: already return-early on non-http
        schemes (jd_fetch/service.py) and no path iterates the jobs table to re-fetch by url,
        so a manual:// row is never fetched.
      - dead_urls / G1-G5 gates: only ever see agent candidate-pool http urls, never the
        jobs table — a paste row (no fetch) never enters them.
      - normalize_job_url: already passes any non-http scheme through unchanged (no code needed).
    """
    # "url provided" = the key is present (even if empty). An empty/whitespace url
    # is a malformed URL, not a paste — routing it through ingest_from_url keeps
    # the original 400 "URL must start with http://…" behaviour rather than a
    # misleading XOR 422.
    has_url = body.url is not None
    has_paste = bool(
        body.company and body.company.strip()
        and body.title and body.title.strip()
        and body.jd_text and body.jd_text.strip()
    )
    if has_url == has_paste:  # both supplied, or neither
        raise HTTPException(
            status_code=422,
            detail="Provide either `url` or all of `company`+`title`+`jd_text`, not both.",
        )

    if has_url:
        result = ingest_from_url(db, workspace, body.url)
    else:
        result = ingest_from_paste(
            db, workspace, company=body.company, title=body.title, jd_text=body.jd_text
        )

    return JobImportResponse(
        job=_job_read(result.job),
        created=result.created,
        jd_fetched=result.jd_fetched,
    )


@router.post("/batch-archive", response_model=BatchArchiveResponse)
def batch_archive(
    body: BatchArchiveRequest,
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
) -> BatchArchiveResponse:
    """Archive multiple jobs at once."""
    if not body.job_ids or len(body.job_ids) > 200:
        raise HTTPException(status_code=400, detail="Provide 1–200 job_ids.")

    run_repo = RunRepository(db)
    job_repo = JobRepository(db)
    workspace_run_ids = {r.id for r in run_repo.list_for_workspace(workspace.id, limit=10_000)}

    archived = 0
    for job_id in body.job_ids:
        job = job_repo.get(job_id)
        if not job or job.discovered_run_id not in workspace_run_ids:
            continue
        job_repo.set_status(job_id, "archived")
        archived += 1

    db.commit()
    return BatchArchiveResponse(archived_count=archived)


@router.post("/batch-analyze", response_model=BatchAnalyzeResponse)
def batch_analyze(
    body: BatchAnalyzeRequest,
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
) -> BatchAnalyzeResponse:
    """Trigger fit analysis for multiple jobs.

    Jobs with an existing job report get a fit_report run directly.
    Jobs without a job report get a job_report run first, which
    auto-chains into a fit_report run upon completion.
    """
    if not body.job_ids or len(body.job_ids) > 50:
        raise HTTPException(status_code=400, detail="Provide 1–50 job_ids.")

    import uuid as _uuid
    from packages.domain.agent_jobs.routing import celery_queue_for_task_type
    from packages.contracts.tasks.envelopes import TaskEnvelope

    run_repo = RunRepository(db)
    task_repo = TaskRepository(db)
    job_repo = JobRepository(db)
    report_repo = JobReportRepository(db)

    workspace_run_ids = {r.id for r in run_repo.list_for_workspace(workspace.id, limit=10_000)}
    profile_id = body.profile_id

    # A client-supplied profile_id is threaded into the fit_report (directly,
    # and via job_report's auto_fit_profile_id auto-chain) and now actually
    # selects which profile the fit is scored against — so verify ownership
    # here, at the entry point, rather than only failing the async run in the
    # worker. Mirrors the job_discovery/run_reflection cross-workspace checks in
    # apps/api/routes/runs.py::create_run.
    if profile_id:
        profile = ProfileRepository(db).get_by_id(profile_id)
        if profile is None or profile.workspace_id != workspace.id:
            raise HTTPException(
                status_code=403,
                detail="profile_id does not belong to this workspace.",
            )

    run_ids: list[str] = []
    skipped: list[str] = []
    report_first: list[str] = []

    for job_id in body.job_ids:
        job = job_repo.get(job_id)
        if not job or job.discovered_run_id not in workspace_run_ids:
            skipped.append(job_id)
            continue
        if job.status == "discovered":
            skipped.append(job_id)
            continue

        job_report = report_repo.get_latest_active(job_id)
        correlation_id = str(_uuid.uuid4())

        if job_report:
            run = run_repo.create(
                workspace_id=workspace.id,
                run_type="fit_report",
                input_snapshot_json={
                    "job_id": job_id,
                    "job_report_id": job_report.id,
                    "force_refresh": False,
                    "profile_id": profile_id,
                },
                correlation_id=correlation_id,
            )
            task_type = "fit_report"
        else:
            run = run_repo.create(
                workspace_id=workspace.id,
                run_type="job_report",
                input_snapshot_json={
                    "job_id": job_id,
                    "use_research": False,
                    "force_refresh": False,
                    "auto_fit_profile_id": profile_id,
                },
                correlation_id=correlation_id,
            )
            task_type = "job_report"
            report_first.append(job_id)

        task = task_repo.create(
            run_id=run.id,
            workspace_id=workspace.id,
            task_type=task_type,
            idempotency_key=f"{task_type}:{workspace.id}:{run.id}",
        )
        db.flush()

        envelope = TaskEnvelope(
            task_id=task.id,
            run_id=run.id,
            workspace_id=workspace.id,
            task_type=task_type,
            idempotency_key=f"{task_type}:{workspace.id}:{run.id}",
            correlation_id=correlation_id,
        )
        celery_queue = celery_queue_for_task_type(task_type)
        try:
            celery_app = _get_celery()
            celery_app.send_task(
                "apps.worker.tasks.execute_task",
                kwargs={"envelope": envelope.model_dump(mode="json")},
                queue=celery_queue,
            )
        except Exception as exc:
            logger.warning("batch_analyze: failed to enqueue %s for job %s: %s", task_type, job_id, exc)

        run_ids.append(run.id)

    db.commit()
    return BatchAnalyzeResponse(run_ids=run_ids, skipped=skipped, report_first=report_first)


@router.get("/{job_id}", response_model=JobRead)
def get_job(
    job_id: str,
    include_report_summary: bool = Query(False),
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
) -> JobRead:
    """Fetch a single job record by ID, verified to belong to the current workspace."""
    job = _get_workspace_job(db, workspace, job_id)

    report = None
    if include_report_summary:
        report = JobReportRepository(db).get_latest_active(job_id)

    is_favorited = JobFavoriteRepository(db).is_favorited(workspace.id, job_id)
    is_not_interested = JobNotInterestedRepository(db).is_not_interested(workspace.id, job_id)
    return _job_read(
        job,
        report,
        include_jd_structured=True,
        is_favorited=is_favorited,
        is_not_interested=is_not_interested,
    )


@router.delete("/{job_id}", status_code=204)
def archive_job(
    job_id: str,
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
):
    """Soft-delete a job by setting its status to 'archived'."""
    _get_workspace_job(db, workspace, job_id)

    JobRepository(db).set_status(job_id, "archived")
    db.commit()


@router.post("/{job_id}/favorite", response_model=FavoriteResponse)
def favorite_job(
    job_id: str,
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
) -> FavoriteResponse:
    """Bookmark a job in the current workspace. Idempotent."""
    _get_workspace_job(db, workspace, job_id)

    JobFavoriteRepository(db).add(workspace.id, job_id)
    db.commit()
    return FavoriteResponse(favorited=True)


@router.delete("/{job_id}/favorite", response_model=FavoriteResponse)
def unfavorite_job(
    job_id: str,
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
) -> FavoriteResponse:
    """Remove a job bookmark in the current workspace. Idempotent."""
    _get_workspace_job(db, workspace, job_id)

    JobFavoriteRepository(db).remove(workspace.id, job_id)
    db.commit()
    return FavoriteResponse(favorited=False)


@router.post("/{job_id}/not-interested", response_model=NotInterestedResponse)
def mark_not_interested(
    job_id: str,
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
) -> NotInterestedResponse:
    """Dismiss a job as not interested in the current workspace. Idempotent."""
    _get_workspace_job(db, workspace, job_id)

    JobNotInterestedRepository(db).add(workspace.id, job_id)
    db.commit()
    return NotInterestedResponse(not_interested=True)


@router.delete("/{job_id}/not-interested", response_model=NotInterestedResponse)
def unmark_not_interested(
    job_id: str,
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
) -> NotInterestedResponse:
    """Remove a job's not-interested dismissal in the current workspace. Idempotent."""
    _get_workspace_job(db, workspace, job_id)

    JobNotInterestedRepository(db).remove(workspace.id, job_id)
    db.commit()
    return NotInterestedResponse(not_interested=False)

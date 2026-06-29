"""
Jobs API — read, archive, and import job records.

Contract:
  GET    /api/app/jobs?status=&limit=&offset=&include_report_summary=  → JobList
  GET    /api/app/jobs/{job_id}                → JobRead
  POST   /api/app/jobs/import                  → JobImportResponse
  DELETE /api/app/jobs/{job_id}                → 204 (soft-delete: sets status to "archived")

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
    JDStructured,
    JobImportRequest,
    JobImportResponse,
    JobList,
    JobRead,
)
from packages.infrastructure.db.models import Workspace
from packages.infrastructure.db.repositories import (
    JobRepository,
    JobReportRepository,
    RunRepository,
    TaskRepository,
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


def _job_read(job, report=None, include_jd_structured: bool = False) -> JobRead:
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

    items, total = JobRepository(db).list(
        run_ids=run_ids,
        status=status,
        limit=limit,
        offset=offset,
    )

    report_map = {}
    if include_report_summary and items:
        job_ids = [j.id for j in items]
        report_map = JobReportRepository(db).get_latest_active_map(job_ids)

    return JobList(
        items=[_job_read(j, report_map.get(j.id)) for j in items],
        total=total,
    )


@router.post("/import", response_model=JobImportResponse, status_code=200)
def import_job(
    body: JobImportRequest,
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
) -> JobImportResponse:
    """Import a single job by URL: fetch JD, extract fields, persist."""
    url = body.url.strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="URL must start with http:// or https://")

    _BLOCKED_HOSTS = ("linkedin.com", "www.linkedin.com")
    from urllib.parse import urlparse
    if urlparse(url).hostname in _BLOCKED_HOSTS:
        raise HTTPException(
            status_code=400,
            detail="LinkedIn requires login to view job postings. Please use the direct employer or ATS URL instead.",
        )

    from packages.infrastructure.llm.usage_writer import set_llm_context
    set_llm_context(call_site="manual_import")

    job_repo = JobRepository(db)

    existing = job_repo.get_by_canonical_url(url)
    if existing:
        run = RunRepository(db).get(existing.discovered_run_id) if existing.discovered_run_id else None
        if run and run.workspace_id != workspace.id:
            raise HTTPException(status_code=409, detail="Job already exists in another workspace.")
        return JobImportResponse(
            job=_job_read(existing),
            created=False,
            jd_fetched=existing.jd_text is not None,
        )

    from packages.domain.agent_jobs.ats_providers import extract_board_info
    from packages.domain.agent_jobs.source_registry import normalize_source_type
    from packages.infrastructure.jd_fetch import fetch_jd_from_url
    from packages.infrastructure.llm.client import get_llm_client
    from packages.infrastructure.llm.jd_extractor import extract_jd_fields

    board_info = extract_board_info(url)
    if board_info:
        raw_source_type = board_info[0]
    else:
        raw_source_type = "unknown"
    norm_source_type, norm_provider = normalize_source_type(raw_source_type)

    run_repo = RunRepository(db)
    task_repo = TaskRepository(db)
    run = run_repo.create(
        workspace_id=workspace.id,
        run_type="manual_import",
        input_snapshot_json={"url": url, "source": "manual_import"},
    )
    task = task_repo.create(
        run_id=run.id,
        workspace_id=workspace.id,
        task_type="manual_import",
        idempotency_key=f"manual_import:{workspace.id}:{url}",
    )
    db.flush()

    jd_fetched = False
    jd_text = None
    jd_hash = None
    jd_structured = None
    status = "discovered"
    title = ""
    company = ""
    location = None

    if board_info:
        from packages.domain.agent_jobs.ats_providers import build_api_url, parse_board_response
        import httpx
        provider, token = board_info
        api_url = build_api_url(provider, token)
        if api_url:
            try:
                resp = httpx.get(api_url, timeout=10.0)
                if resp.status_code == 200:
                    for bj in parse_board_response(provider, resp.json()):
                        if bj.url == url:
                            title = bj.title
                            company = bj.company
                            location = bj.location
                            break
            except Exception:
                pass
        if not company:
            company = token.replace("-", " ").title()

    try:
        fetch_result = fetch_jd_from_url(url)
        if fetch_result.ok and fetch_result.jd_text:
            jd_text = fetch_result.jd_text
            jd_hash = fetch_result.jd_hash
            jd_fetched = True
            status = "reportable"
            try:
                jd_structured = extract_jd_fields(
                    jd_text=jd_text,
                    company=company,
                    title=title,
                    location=location or "",
                    llm_client=get_llm_client(),
                )
            except Exception:
                logger.warning("import_job: JD extraction failed for %s", url, exc_info=True)
    except Exception:
        logger.warning("import_job: JD fetch failed for %s", url, exc_info=True)

    if not title and jd_text:
        for line in jd_text.splitlines():
            line = line.strip()
            if line.lower().startswith("title:"):
                title = line[6:].strip()
                break
    if not title:
        slug = url.rstrip("/").split("/")[-1].split("?")[0]
        title = re.sub(r"[_-](?:JR?\d+)$", "", slug, flags=re.IGNORECASE).replace("-", " ").replace("_", " ").strip().title() or "Imported Job"
    if not company:
        from urllib.parse import urlparse
        hostname = urlparse(url).hostname or ""
        company = hostname.split(".")[0].replace("-", " ").title() if hostname else ""

    job = job_repo.create(
        canonical_url=url,
        source_url=url,
        source_type=norm_source_type,
        source_provider=norm_provider,
        title=title,
        company=company,
        jd_text=jd_text,
        jd_hash=jd_hash,
        raw_payload_json={
            "source": "manual_import",
            "jd_structured": jd_structured,
            "fetch_status": "success" if jd_fetched else "failed",
        },
        status=status,
        discovered_run_id=run.id,
        discovered_task_id=task.id,
    )

    task_repo.mark_succeeded(task.id)
    run_repo.complete(run.id, status="succeeded", result_summary={
        "job_id": job.id,
        "jd_fetched": jd_fetched,
        "source": "manual_import",
    })
    db.commit()

    logger.info("import_job: created job %s from %s (status=%s)", job.id, url, status)

    return JobImportResponse(
        job=_job_read(job),
        created=True,
        jd_fetched=jd_fetched,
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
    job = JobRepository(db).get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found.")

    if not job.discovered_run_id:
        raise HTTPException(status_code=403, detail="Access denied.")
    run = RunRepository(db).get(job.discovered_run_id)
    if run is None or run.workspace_id != workspace.id:
        raise HTTPException(status_code=403, detail="Access denied.")

    report = None
    if include_report_summary:
        report = JobReportRepository(db).get_latest_active(job_id)

    return _job_read(job, report, include_jd_structured=True)


@router.delete("/{job_id}", status_code=204)
def archive_job(
    job_id: str,
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
):
    """Soft-delete a job by setting its status to 'archived'."""
    job = JobRepository(db).get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found.")

    if not job.discovered_run_id:
        raise HTTPException(status_code=403, detail="Access denied.")
    run = RunRepository(db).get(job.discovered_run_id)
    if run is None or run.workspace_id != workspace.id:
        raise HTTPException(status_code=403, detail="Access denied.")

    JobRepository(db).set_status(job_id, "archived")
    db.commit()

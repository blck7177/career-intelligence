"""
Jobs API — read discovered job records.

Contract:
  GET /api/jobs?status=&limit=&offset=&include_report_summary=  → JobList
  GET /api/jobs/{job_id}                → JobRead

These are read-only endpoints. Job records are written by the worker/validator gate,
not by the API. Results are always scoped to the authenticated user's workspace.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from apps.api.dependencies.auth import get_current_workspace
from apps.api.dependencies.db import get_db
from packages.contracts.api.jobs import JobList, JobRead
from packages.infrastructure.db.models import Workspace
from packages.infrastructure.db.repositories import JobRepository, JobReportRepository, RunRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/app/jobs", tags=["jobs"])


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


def _job_read(job, report=None) -> JobRead:
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
        data["primary_workstream"] = s.get("primary_workstream")
        data["workstream_confidence"] = s.get("workstream_confidence")
        pf = s.get("position_function") or {}
        if isinstance(pf, dict) and pf.get("confidence"):
            # Prefer function confidence as fallback when workstream confidence absent
            if not data["workstream_confidence"]:
                data["workstream_confidence"] = pf.get("confidence")
        data["seniority_inferred"] = _infer_seniority_from_title(job.title)
    return JobRead.model_validate(data)


@router.get("", response_model=JobList)
def list_jobs(
    status: Optional[str] = Query(None, description="Filter by job status: discovered|reportable|invalid|stale"),
    include_report_summary: bool = Query(
        False,
        description="Join latest active job report for workstream/seniority/confidence fields",
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

    return _job_read(job, report)

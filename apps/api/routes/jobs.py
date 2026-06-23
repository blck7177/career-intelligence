"""
Jobs API — read discovered job records.

Contract:
  GET /api/jobs?workspace_id=&status=&limit=&offset=  → JobList
  GET /api/jobs/{job_id}                               → JobRead

These are read-only endpoints. Job records are written by the worker/validator gate,
not by the API. This layer does NOT touch the discovery/report pipeline.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from apps.api.dependencies.db import get_db
from packages.contracts.api.jobs import JobList, JobRead
from packages.infrastructure.db.repositories import JobRepository, RunRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("", response_model=JobList)
def list_jobs(
    workspace_id: Optional[str] = Query(None, description="Filter by workspace. If omitted, returns all jobs."),
    status: Optional[str] = Query(None, description="Filter by job status: discovered|reportable|invalid|stale"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> JobList:
    """List discovered job records, optionally scoped to a workspace."""
    run_ids: Optional[list[str]] = None
    if workspace_id:
        runs = RunRepository(db).list_for_workspace(workspace_id, limit=10_000)
        run_ids = [r.id for r in runs]
        if not run_ids:
            return JobList(items=[], total=0)

    items, total = JobRepository(db).list(
        run_ids=run_ids,
        status=status,
        limit=limit,
        offset=offset,
    )
    return JobList(items=[JobRead.model_validate(j) for j in items], total=total)


@router.get("/{job_id}", response_model=JobRead)
def get_job(job_id: str, db: Session = Depends(get_db)) -> JobRead:
    """Fetch a single job record by ID."""
    job = JobRepository(db).get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found.")
    return JobRead.model_validate(job)

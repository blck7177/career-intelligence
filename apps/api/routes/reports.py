"""
Reports API — read job intelligence reports and candidate fit reports.

Contract:
  GET /api/job-reports/{job_report_id}          → JobReportResponse
  GET /api/fit-reports/{fit_report_id}           → FitReportResponse
  GET /api/jobs/{job_id}/job-reports/latest      → JobReportResponse
  GET /api/runs/{run_id}/report                  → JobReportResponse | FitReportResponse
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from apps.api.dependencies.db import get_db
from packages.infrastructure.db.repositories import (
    FitReportRepository,
    JobReportRepository,
    RunRepository,
    TaskRepository,
    TaskEventRepository,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["reports"])


# ---------------------------------------------------------------------------
# Response DTOs
# ---------------------------------------------------------------------------


class JobReportResponse(BaseModel):
    id: str
    job_id: str
    status: str
    jd_hash: str
    prompt_version: str
    used_research: bool
    research_bundle_hash: Optional[str] = None
    structured_json: dict[str, Any]
    summary_json: dict[str, Any]
    narrative_artifact_id: Optional[str] = None
    structured_artifact_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class FitReportResponse(BaseModel):
    id: str
    workspace_id: str
    job_id: str
    job_report_id: str
    candidate_profile_id: Optional[str] = None
    overall_match_score: int
    status: str
    prompt_version: str
    structured_json: dict[str, Any]
    summary_json: dict[str, Any]
    narrative_artifact_id: Optional[str] = None
    structured_artifact_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _job_report_response(row) -> JobReportResponse:
    return JobReportResponse(
        id=row.id,
        job_id=row.job_id,
        status=row.status,
        jd_hash=row.jd_hash or "",
        prompt_version=row.prompt_version or "",
        used_research=bool(row.used_research),
        research_bundle_hash=row.research_bundle_hash,
        structured_json=row.structured_json or {},
        summary_json=row.summary_json or {},
        narrative_artifact_id=row.narrative_artifact_id,
        structured_artifact_id=row.structured_artifact_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _fit_report_response(row) -> FitReportResponse:
    return FitReportResponse(
        id=row.id,
        workspace_id=row.workspace_id,
        job_id=row.job_id,
        job_report_id=row.job_report_id,
        candidate_profile_id=row.candidate_profile_id,
        overall_match_score=row.overall_match_score or 0,
        status=row.status,
        prompt_version=row.prompt_version or "",
        structured_json=row.structured_json or {},
        summary_json=row.summary_json or {},
        narrative_artifact_id=row.narrative_artifact_id,
        structured_artifact_id=row.structured_artifact_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/job-reports/{job_report_id}", response_model=JobReportResponse)
def get_job_report(job_report_id: str, db: Session = Depends(get_db)):
    """Fetch a specific Job Intelligence Report by ID."""
    row = JobReportRepository(db).get(job_report_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Job report {job_report_id!r} not found.")
    return _job_report_response(row)


@router.get("/fit-reports/{fit_report_id}", response_model=FitReportResponse)
def get_fit_report(fit_report_id: str, workspace_id: str, db: Session = Depends(get_db)):
    """
    Fetch a specific Candidate Fit Report by ID.

    workspace_id is required — FitReports are workspace-private.
    Returns 403 if the report does not belong to the given workspace.
    """
    row = FitReportRepository(db).get(fit_report_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Fit report {fit_report_id!r} not found.")
    if row.workspace_id != workspace_id:
        raise HTTPException(status_code=403, detail="Workspace mismatch.")
    return _fit_report_response(row)


@router.get("/jobs/{job_id}/job-reports/latest", response_model=JobReportResponse)
def get_latest_job_report(job_id: str, db: Session = Depends(get_db)):
    """Fetch the latest active Job Intelligence Report for a job."""
    row = JobReportRepository(db).get_latest_active(job_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"No active Job Intelligence Report found for job {job_id!r}.",
        )
    return _job_report_response(row)


@router.get("/runs/{run_id}/report")
def get_run_report(run_id: str, db: Session = Depends(get_db)):
    """
    Return the report generated by a job_report or fit_report run.

    Primary path: reads run.result_summary_json for the report_id (structured contract).
    Legacy fallback: scans task_succeeded event messages for "job_report_id=" / "fit_report_id=".
    """
    run = RunRepository(db).get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id!r} not found.")

    if run.run_type not in ("job_report", "fit_report"):
        raise HTTPException(
            status_code=400,
            detail=f"Run {run_id!r} has type {run.run_type!r}; only job_report and fit_report runs produce reports.",
        )

    # Primary path: structured result_summary_json written by worker on success.
    report_id: Optional[str] = None
    summary = run.result_summary_json or {}
    report_id = summary.get("report_id") or None

    # Legacy fallback: scan task_succeeded event messages.
    # Kept for backward compat with runs created before result_summary_json was stamped.
    if not report_id:
        events = TaskEventRepository(db).list_for_run(run_id)
        for event in events:
            # Try structured payload_json first (also added in the same release)
            if event.event_type == "task_succeeded" and event.payload_json:
                report_id = event.payload_json.get("report_id") or None
                if report_id:
                    break
            # Last-resort: parse human-readable message string
            if event.event_type == "task_succeeded" and event.message and not report_id:
                if run.run_type == "job_report":
                    for part in event.message.split():
                        if part.startswith("job_report_id="):
                            report_id = part.split("=", 1)[1]
                            break
                elif run.run_type == "fit_report":
                    for part in event.message.split():
                        if part.startswith("fit_report_id="):
                            report_id = part.split("=", 1)[1]
                            break
            if report_id:
                break

    if not report_id:
        raise HTTPException(
            status_code=404,
            detail="Report not yet generated for this run.",
        )

    if run.run_type == "job_report":
        row = JobReportRepository(db).get(report_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"Job report {report_id!r} not found.")
        return _job_report_response(row)
    else:
        row = FitReportRepository(db).get(report_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"Fit report {report_id!r} not found.")
        # Workspace check: run.workspace_id must match the fit report's workspace
        if row.workspace_id != run.workspace_id:
            raise HTTPException(status_code=403, detail="Workspace mismatch.")
        return _fit_report_response(row)

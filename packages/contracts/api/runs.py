"""
API DTOs for runs and tasks.

These are the only objects the frontend sees.
OpenClaw session keys, skill paths, and agent internals are NOT included.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

RunStatus = Literal["queued", "running", "succeeded", "failed", "cancelled", "needs_review"]
TaskStatus = Literal["queued", "running", "succeeded", "failed", "cancelled", "needs_review"]


class FailedValidatorSummary(BaseModel):
    """One validator's failure detail within a needs_review result_summary."""

    name: str
    errors: list[dict] = Field(default_factory=list)


class RunResultSummary(BaseModel):
    """
    Structured diagnostic payload written by the worker at run completion.

    Populated for both terminal statuses:
      - validation_status="passed"  → run succeeded; candidate_count / job_ids present
      - validation_status="failed"  → run needs_review; phase / failed_validators present

    All fields except validation_status are Optional because the exact set depends
    on which execution phase produced the summary.
    """

    validation_status: Literal["passed", "failed"]
    phase: Optional[str] = None
    error_code: Optional[str] = None
    invocation_id: Optional[str] = None
    candidate_count: Optional[int] = None
    sources_tried: Optional[int] = None
    # succeeded path
    job_ids: Optional[list[str]] = None
    artifact_ids: Optional[list[str]] = None
    # needs_review path
    failed_validators: Optional[list[FailedValidatorSummary]] = None
    artifact_paths: Optional[dict[str, str]] = None


class RunCreate(BaseModel):
    """Request body for POST /api/runs."""

    run_type: str = Field(..., examples=["job_discovery"])
    input_snapshot: dict = Field(default_factory=dict)


class RunRead(BaseModel):
    """Response for GET /api/runs/{run_id}."""

    id: str
    workspace_id: str
    run_type: str
    status: RunStatus
    correlation_id: Optional[str] = None
    schema_version: str = "v1"
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    result_summary: Optional[RunResultSummary] = Field(None, alias="result_summary_json")
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True, "populate_by_name": True}


class RunList(BaseModel):
    """Response for GET /api/runs."""

    items: list[RunRead]
    total: int


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------


class TaskRead(BaseModel):
    """Response for GET /api/runs/{run_id}/tasks."""

    id: str
    run_id: str
    workspace_id: str
    task_type: str
    status: TaskStatus
    attempt_count: int
    max_attempts: int
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    queued_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# TaskEvent
# ---------------------------------------------------------------------------


class TaskEventRead(BaseModel):
    id: str
    task_id: str
    run_id: str
    event_type: str
    message: Optional[str] = None
    payload: Optional[dict] = Field(None, alias="payload_json")
    created_at: datetime

    model_config = {"from_attributes": True, "populate_by_name": True}


# ---------------------------------------------------------------------------
# AgentInvocation (debug endpoint, hidden from regular users)
# ---------------------------------------------------------------------------


class AgentInvocationRead(BaseModel):
    id: str
    run_id: str
    task_id: str
    agent_id: str
    status: str
    skill_contract_version: str
    exit_code: Optional[int] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}

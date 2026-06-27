"""
API DTOs for runs and tasks.

These are the only objects the frontend sees.
OpenClaw session keys, skill paths, and agent internals are NOT included.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, RootModel

from packages.contracts.api.discovery import JobDiscoveryFrontendInput


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

    validation_status: Optional[Literal["passed", "failed"]] = None
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
    # profile_import path
    import_type: Optional[str] = None
    profile_draft: Optional[dict] = None
    parse_notes: Optional[dict] = None


# ---------------------------------------------------------------------------
# Per-run-type input schemas
# ---------------------------------------------------------------------------


class JobReportInput(BaseModel):
    """Input for run_type=job_report."""

    job_id: str
    use_research: bool = True
    force_refresh: bool = False
    research_artifact_id: Optional[str] = None


class FitReportInput(BaseModel):
    """Input for run_type=fit_report."""

    job_id: str
    job_report_id: Optional[str] = None
    force_refresh: bool = False


class ProfileImportInput(BaseModel):
    """Input for run_type=profile_import."""

    resume_text: str = Field(..., min_length=1, max_length=50_000)
    source_type: Literal["paste"] = "paste"


class JobResearchInput(BaseModel):
    """Input for run_type=job_research."""

    job_id: str
    max_tool_calls: int = Field(default=20, ge=1, le=100)
    timeout_seconds: int = Field(default=600, ge=60, le=3600)
    model_config = ConfigDict(extra="allow")


class RunReflectionInput(BaseModel):
    """Input for run_type=run_reflection."""

    run_id: str
    max_tool_calls: int = Field(default=10, ge=1, le=100)
    timeout_seconds: int = Field(default=300, ge=60, le=3600)
    model_config = ConfigDict(extra="allow")


# ---------------------------------------------------------------------------
# RunCreate — discriminated union on run_type
# ---------------------------------------------------------------------------


class JobDiscoveryRunCreate(BaseModel):
    """POST /api/app/runs with run_type=job_discovery."""

    run_type: Literal["job_discovery"]
    input_snapshot: JobDiscoveryFrontendInput


class JobReportRunCreate(BaseModel):
    """POST /api/app/runs with run_type=job_report."""

    run_type: Literal["job_report"]
    input_snapshot: JobReportInput


class FitReportRunCreate(BaseModel):
    """POST /api/app/runs with run_type=fit_report."""

    run_type: Literal["fit_report"]
    input_snapshot: FitReportInput


class ProfileImportRunCreate(BaseModel):
    """POST /api/app/runs with run_type=profile_import."""

    run_type: Literal["profile_import"]
    input_snapshot: ProfileImportInput


class JobResearchRunCreate(BaseModel):
    """POST /api/app/runs with run_type=job_research."""

    run_type: Literal["job_research"]
    input_snapshot: JobResearchInput


class RunReflectionRunCreate(BaseModel):
    """POST /api/app/runs with run_type=run_reflection."""

    run_type: Literal["run_reflection"]
    input_snapshot: RunReflectionInput


_RunCreateUnion = Annotated[
    Union[
        JobDiscoveryRunCreate,
        JobReportRunCreate,
        FitReportRunCreate,
        ProfileImportRunCreate,
        JobResearchRunCreate,
        RunReflectionRunCreate,
    ],
    Field(discriminator="run_type"),
]


class RunCreate(RootModel[_RunCreateUnion]):
    """Request body for POST /api/app/runs — discriminated by run_type."""

    @property
    def run_type(self) -> str:
        return self.root.run_type

    @property
    def input_snapshot(self) -> BaseModel:
        return self.root.input_snapshot


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

"""
API DTOs for the application tracker.

Every application references a job row (job_id required — URL-imported or
paste-created via the shared manual_import pipeline; there are no bare rows).
Status transitions are validated by packages/domain/applications/transitions.py;
the create endpoint only accepts the two entry states (planned/applied), all
other moves go through POST /applications/{id}/transition.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

# Keep in lockstep with packages/domain/applications/transitions.STATUSES
# (a test asserts equality).
ApplicationStatus = Literal[
    "planned",
    "applied",
    "in_review",
    "interviewing",
    "offer",
    "rejected",
    "withdrawn",
    "ghosted",
]
ApplicationStatusGroup = Literal["planned", "active", "closed"]
ActionType = Literal[
    "apply", "follow_up", "networking", "prep", "thank_you", "custom", "global"
]


class ApplicationJobRef(BaseModel):
    """Lean projection of the referenced Job for list/detail rows."""

    id: str
    title: str
    company: str
    canonical_url: str
    status: str
    model_config = {"from_attributes": True}


class ApplicationCreate(BaseModel):
    """Create an application for an existing job. status is limited to the two
    entry states; later moves go through the transition endpoint."""

    job_id: str
    status: Literal["planned", "applied"] = "planned"
    channel: Optional[str] = None
    lane: Optional[str] = None
    excitement: Optional[int] = Field(None, ge=1, le=3)
    applied_at: Optional[datetime] = None
    profile_id: Optional[str] = None
    resume_run_id: Optional[str] = None
    contact_name: Optional[str] = None
    contact_note: Optional[str] = None
    notes: Optional[str] = None


class ApplicationUpdate(BaseModel):
    """Partial field edit. Excludes status (transition endpoint) and the
    immutable job_id/workspace_id."""

    profile_id: Optional[str] = None
    lane: Optional[str] = None
    excitement: Optional[int] = Field(None, ge=1, le=3)
    channel: Optional[str] = None
    applied_at: Optional[datetime] = None
    resume_run_id: Optional[str] = None
    contact_name: Optional[str] = None
    contact_note: Optional[str] = None
    notes: Optional[str] = None
    closed_reason: Optional[str] = None


class StatusTransition(BaseModel):
    status: ApplicationStatus
    note: Optional[str] = None
    force: bool = False


class ApplicationEventRead(BaseModel):
    id: str
    event_type: str
    message: Optional[str] = None
    payload_json: Optional[dict] = None
    created_at: datetime
    model_config = {"from_attributes": True}


class ActionCreate(BaseModel):
    type: ActionType
    title: str = Field(..., min_length=1, max_length=512)
    application_id: Optional[str] = None
    due_at: Optional[datetime] = None


class ActionUpdate(BaseModel):
    op: Literal["complete", "snooze", "dismiss"]
    snooze_days: int = Field(1, ge=1, le=90)


class ActionRead(BaseModel):
    id: str
    application_id: Optional[str] = None
    type: str
    title: str
    due_at: Optional[datetime] = None
    status: str
    auto_generated: bool
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class ActionList(BaseModel):
    items: list[ActionRead]
    total: int


class ApplicationRead(BaseModel):
    id: str
    job_id: str
    profile_id: Optional[str] = None
    status: str
    lane: Optional[str] = None
    excitement: Optional[int] = None
    channel: Optional[str] = None
    applied_at: Optional[datetime] = None
    resume_run_id: Optional[str] = None
    contact_name: Optional[str] = None
    contact_note: Optional[str] = None
    notes: Optional[str] = None
    closed_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    # Derived / joined (not ORM columns):
    job: Optional[ApplicationJobRef] = None
    next_action_due_at: Optional[datetime] = None
    model_config = {"from_attributes": True}


class ApplicationDetail(ApplicationRead):
    events: list[ApplicationEventRead] = Field(default_factory=list)
    actions: list[ActionRead] = Field(default_factory=list)
    # Latest active fit report for the referenced job (detail-only — kept off the
    # list row to avoid an N+1 fit lookup per row).
    fit_score: Optional[int] = None
    fit_report_id: Optional[str] = None


class ApplicationList(BaseModel):
    items: list[ApplicationRead]
    total: int


class ApplicationSummary(BaseModel):
    """Counts for the TopBar badge + Home StatStrip."""

    today_due: int
    active: int
    planned: int
    needs_action: int
    by_status: dict[str, int]


class WeeklyTarget(BaseModel):
    apply: int = 10
    outreach: int = 5
    follow_up: int = 6


class PlannerSettings(BaseModel):
    """All planner-tunable numbers, with product defaults. P0 is read-only
    (defaults merged over workspaces.planner_settings_json); PUT lands in P1."""

    weekly_target: WeeklyTarget = Field(default_factory=WeeklyTarget)
    daily_cap_minutes: int = 90
    rest_days: list[str] = Field(default_factory=lambda: ["sat", "sun"])
    follow_up_days: int = 7
    ghost_days: int = 14
    interview_checkin_days: int = 7
    fresh_window_days: int = 3
    apply_or_drop_days: int = 14
    onsite_target: int = 4
    active_target: int = 15
    review_day: str = "sun"

"""
API DTOs for the application tracker.

Every application references a job row (job_id required — URL-imported or
paste-created via the shared manual_import pipeline; there are no bare rows).
Status transitions are validated by packages/domain/applications/transitions.py;
the create endpoint only accepts the two entry states (planned/applied), all
other moves go through POST /applications/{id}/transition.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AliasChoices, BaseModel, Field, field_validator

# The weekday vocabulary `rest_days` / `review_day` accept — and, because the
# ORDER matches date.weekday() (Monday == 0), also the index the planner uses to
# turn a local date into one of those keys. Ordered on purpose: the domain
# modules index into it, so this tuple must never be reordered or turned back
# into a set. One definition, imported by rules.py and week.py, so a workspace's
# rest days can't mean one thing to the validator and another to the engine.
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

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
    # Employer posting date if known (ATS-captured); lets the planned queue show
    # true "posted Xd" instead of the application's "seen Xd".
    posted_at: Optional[datetime] = None
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


InterviewRound = Literal["recruiter_screen", "phone", "onsite", "final"]


class ApplicationEventCreate(BaseModel):
    """Body for POST /applications/{id}/events. Two whitelisted kinds (the client
    cannot forge status_changed — the enum rejects it):
      - note (default): a freeform timeline note (message required).
      - interview_scheduled: a scheduled round (round_type + at required); the
        rules engine reads these to drive thank_you/check_in.
    Cross-field requirements are enforced at the route layer (repo convention)."""

    event_type: Literal["note", "interview_scheduled"] = "note"
    message: Optional[str] = Field(None, max_length=2000)
    round_type: Optional[InterviewRound] = None
    at: Optional[datetime] = None


class ActionCreate(BaseModel):
    """A manual to-do. est_minutes is the user's own effort estimate; omitting it
    leaves the row NULL and the Today view falls back to a per-type default."""

    type: ActionType
    title: str = Field(..., min_length=1, max_length=512)
    application_id: Optional[str] = None
    due_at: Optional[datetime] = None
    est_minutes: Optional[int] = Field(None, ge=5, le=480)


class ActionUpdate(BaseModel):
    op: Literal["complete", "snooze", "dismiss"]
    snooze_days: int = Field(1, ge=1, le=90)
    # Absolute snooze target (overrides snooze_days) — "Rest until Monday" sets
    # this so overdue actions land ON Monday, not merely +N days from a past due.
    snooze_until: Optional[datetime] = None


# Payload keys the API may expose. The rules engine writes the facts a rule
# fired on (see packages/domain/planner/rules.py) and the UI renders them into
# "why this exists" copy. Allow-list rather than block-list, so a field added to
# a payload later is invisible to clients until someone deliberately lists it.
PUBLIC_PAYLOAD_KEYS = frozenset(
    {
        "rule",
        "days_since_applied",
        "interview_at",
        "days_since_interview",
        "days_planned",
        "planned_count",
        "target",
    }
)


class ActionRead(BaseModel):
    id: str
    application_id: Optional[str] = None
    type: str
    title: str
    due_at: Optional[datetime] = None
    # No ge/le here (read models don't re-validate, per this file's convention) —
    # legacy rows are NULL and must serialise, not 500.
    est_minutes: Optional[int] = None
    # Times pushed to a later day. 0 is a real value (never deferred), not unknown.
    snooze_count: int = 0
    # Whitelisted rule facts; None for manual rows and anything pre-dating this.
    payload: Optional[dict] = Field(
        None, validation_alias=AliasChoices("payload", "payload_json")
    )
    status: str
    auto_generated: bool
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True, "populate_by_name": True}

    # mode="before": runs ahead of the dict type check, so a row whose
    # payload_json somehow isn't an object degrades to None instead of raising
    # and 500ing the whole Today list. (After-mode would never see it — pydantic
    # would have rejected the value first, making the isinstance guard dead code.)
    @field_validator("payload", mode="before")
    @classmethod
    def _only_public_keys(cls, v: object) -> Optional[dict]:
        if not isinstance(v, dict):
            return None
        kept = {k: val for k, val in v.items() if k in PUBLIC_PAYLOAD_KEYS}
        return kept or None


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
    next_action_type: Optional[str] = None  # type of the soonest pending action (list subline)
    # Latest active fit score for the referenced job. Off by default (no per-row
    # fit lookup); populated only when the list is requested with include_fit=true
    # (the planned queue), via one batched query — never an N+1.
    fit_score: Optional[int] = None
    model_config = {"from_attributes": True}


class ApplicationDetail(ApplicationRead):
    events: list[ApplicationEventRead] = Field(default_factory=list)
    actions: list[ActionRead] = Field(default_factory=list)
    # fit_score is inherited from ApplicationRead; the detail additionally links
    # the report id.
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


class FunnelStage(BaseModel):
    key: str  # planned | applied | in_review | interviewing | onsite | offer
    count: int


class FunnelAlert(BaseModel):
    kind: str  # supply_drought | ghosted_suggestion | check_in | onsite_low
    severity: str  # info | warn
    application_id: Optional[str] = None
    message_key: str  # i18n key the frontend renders with `context`
    context: dict = Field(default_factory=dict)


class FunnelResponse(BaseModel):
    """Pipeline health for the Plan view's Pipeline zone."""

    stages: list[FunnelStage]
    alerts: list[FunnelAlert]


class PlannerWeekInterview(BaseModel):
    """A scheduled round on the week strip, resolved to its company."""

    application_id: str
    company: str
    round_type: Optional[str] = None
    at: datetime


class PlannerWeekDay(BaseModel):
    date: str  # ISO local date (settings.timezone)
    due_count: int
    interviews: list[PlannerWeekInterview] = Field(default_factory=list)
    is_rest: bool
    is_today: bool


class PlannerWeek(BaseModel):
    """The week's shape for the Today card's strip: where the hard commitments
    already are, so the day gets planned around them rather than over them."""

    week_start: str  # ISO date (Monday, settings.timezone)
    days: list[PlannerWeekDay]


class PlannerStats(BaseModel):
    """This-week triplet for the Plan view: done-vs-target on the three weekly
    cadence dimensions (Job Search Quality Scale 2022)."""

    week_start: str  # ISO date (Monday, settings.timezone)
    applied: int
    outreach: int
    follow_ups: int
    weekly_target: WeeklyTarget


class WeeklyTarget(BaseModel):
    apply: int = Field(10, ge=0, le=1000)
    outreach: int = Field(5, ge=0, le=1000)
    follow_up: int = Field(6, ge=0, le=1000)


class PlannerSettings(BaseModel):
    """All planner-tunable numbers, with product defaults. Read merges the stored
    workspaces.planner_settings_json over these defaults; PUT /planner-settings
    (W6) validates a merged result through THIS model, so every constraint /
    validator below is the write-path's guard too."""

    # The single source of truth for the planner's "today": all day-boundary /
    # workday math (rules engine generation AND the Today query/bucketing) uses
    # this zone. due_at is stored as the UTC instant of local-date 00:00 in this
    # zone, so the existing `due_at <= now(utc)` query needs no change.
    timezone: str = "America/New_York"
    weekly_target: WeeklyTarget = Field(default_factory=WeeklyTarget)
    daily_cap_minutes: int = Field(90, ge=0, le=1440)
    rest_days: list[str] = Field(default_factory=lambda: ["sat", "sun"])
    follow_up_days: int = Field(7, ge=1, le=365)
    ghost_days: int = Field(14, ge=1, le=365)
    interview_checkin_days: int = Field(7, ge=1, le=365)
    fresh_window_days: int = Field(3, ge=1, le=365)
    apply_or_drop_days: int = Field(14, ge=1, le=365)
    onsite_target: int = Field(4, ge=0, le=1000)
    active_target: int = Field(15, ge=0, le=1000)
    review_day: str = "sun"
    # ISO date the user marked the start of their search — powers the header's
    # "Week N of search" (computed client-side). None until they set it.
    search_started_at: Optional[str] = None

    @field_validator("timezone")
    @classmethod
    def _valid_timezone(cls, v: str) -> str:
        # A bad tz would break the rules engine (ZoneInfo raises at day-boundary
        # math), so reject at the write boundary rather than 500 later.
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown timezone: {v!r}") from exc
        return v

    @field_validator("rest_days")
    @classmethod
    def _valid_rest_days(cls, v: list[str]) -> list[str]:
        bad = [d for d in v if d not in WEEKDAYS]
        if bad:
            raise ValueError(f"invalid weekday(s): {bad}; expected mon..sun")
        return v

    @field_validator("review_day")
    @classmethod
    def _valid_review_day(cls, v: str) -> str:
        if v not in WEEKDAYS:
            raise ValueError(f"invalid weekday: {v!r}; expected mon..sun")
        return v

    @field_validator("search_started_at")
    @classmethod
    def _valid_search_started_at(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        try:
            date.fromisoformat(v)
        except ValueError as exc:
            raise ValueError("search_started_at must be an ISO date (YYYY-MM-DD)") from exc
        return v


class PlannerSettingsUpdate(BaseModel):
    """Partial update for PUT /planner-settings — every field optional so the
    client can send only what changed. The route merges the set fields over the
    stored JSON and re-validates the result through PlannerSettings (that model
    owns the bounds/validators), so this mirror carries types only."""

    timezone: Optional[str] = None
    weekly_target: Optional[WeeklyTarget] = None
    daily_cap_minutes: Optional[int] = None
    rest_days: Optional[list[str]] = None
    follow_up_days: Optional[int] = None
    ghost_days: Optional[int] = None
    interview_checkin_days: Optional[int] = None
    fresh_window_days: Optional[int] = None
    apply_or_drop_days: Optional[int] = None
    onsite_target: Optional[int] = None
    active_target: Optional[int] = None
    review_day: Optional[str] = None
    search_started_at: Optional[str] = None


# ---------------------------------------------------------------------------
# Weekly review (Wave 5) — the planner's Review zone
# ---------------------------------------------------------------------------


class PlannerDayLogRead(BaseModel):
    """One day's plan-versus-outcome. `null` from the API means the day has no
    row at all — the ritual never ran — which the Plan view shows differently
    from a day committed to nothing."""

    local_date: str  # ISO date in settings.timezone
    committed_est: Optional[int] = None
    done_est: Optional[int] = None
    reflection: Optional[str] = None
    closed_at: Optional[datetime] = None


class PlannerDayRead(BaseModel):
    """Today's planner state.

    Two things that look alike and are not. `log` is the RITUAL record and may
    be null — no row means the morning ritual has not run, which is what the
    banner keys off. done_count/done_est are a MEASUREMENT of what has actually
    been completed today, always present, recomputed on every read: the done bar
    shows them all day, whereas the log's done_est is only written at close."""

    log: Optional[PlannerDayLogRead] = None
    done_count: int = 0
    done_est: int = 0


class PlannerDayCommit(BaseModel):
    """Body of POST /planner-day/commit — the morning ritual's third step.

    The client sends WHICH to-dos it kept, never the total: the stored number
    has to be the server's own arithmetic over the same estimates the capacity
    bar was drawn from, or the weekly comparison is measuring a figure the user
    could have edited. There is no date field either — the day is resolved from
    settings.timezone, so a browser in the wrong zone cannot file a commitment
    against yesterday."""

    kept_action_ids: list[str] = Field(default_factory=list, max_length=500)


class PlannerDayClose(BaseModel):
    """Body of POST /planner-day/close — the evening ritual.

    done_est is deliberately absent for the same reason: it is measured from
    completed_at server-side. All the client contributes is the reflection."""

    reflection: Optional[str] = Field(None, max_length=4000)


class PlannerDayStat(BaseModel):
    """One day's plan versus actual, for the weekly review's per-day strip."""

    date: str  # ISO local date
    committed_est: Optional[int] = None
    done_est: Optional[int] = None


class WeeklyReviewStats(BaseModel):
    """The deterministic numbers a weekly review is built from — computed by the
    PURE aggregator (packages/domain/planner/weekly.py) and stored verbatim in
    planner_reviews.stats_json. Also the payload the LLM narrates from."""

    week_start: str  # ISO date (Monday, settings.timezone)
    # This-week cadence triplet vs targets (same definitions as PlannerStats).
    applied: int
    outreach: int
    follow_ups: int
    weekly_target: WeeklyTarget
    # Current pipeline snapshot (same stages as the funnel).
    funnel: list[FunnelStage]
    # Distribution of tracked applications by effort lane / channel.
    by_lane: dict[str, int] = Field(default_factory=dict)
    by_channel: dict[str, int] = Field(default_factory=dict)
    # Application → interview conversion vs a coaching benchmark.
    applied_total: int  # applications that ever reached "applied" (applied_at set)
    reached_interview: int  # of those, how many got any interview
    interview_rate: float  # reached_interview / applied_total (0 when no applies)
    benchmark_interview_rate: float = 0.08  # Job Search Quality Scale app→screen target
    # Plan versus actual, one entry per day that has a day log. Days the ritual
    # never ran are ABSENT rather than zero-filled: "did not plan" and "planned
    # nothing" are different, and a week of zeroes would read as a bad week
    # instead of an unrecorded one.
    days: list["PlannerDayStat"] = Field(default_factory=list)
    # Honesty flag: pre-Gmail (P2), an employer "reply" is only what the user
    # logged (status advance + manual interview events), never inbox-detected.
    replies_are_manual: bool = True


class WeeklyReviewRead(BaseModel):
    """One weekly review for the Plan view's Review zone. `narrative_md` is the
    LLM summary; when it is None the generation degraded to the pure-number
    template (`degraded == True`) and the card renders stats-only."""

    week_start: str
    stats: WeeklyReviewStats
    narrative_md: Optional[str] = None
    degraded: bool = False
    generated_at: datetime
    # When the user first opened it; None = never. The Plan view's banner exists
    # because of this field: a review nobody reads is a weekly job run for
    # nothing. Regenerating a review with CHANGED content clears it back to None
    # (see PlannerReviewRepository.upsert) — different numbers are a different
    # review, and the user should get the chance to see them.
    read_at: Optional[datetime] = None


class WeeklyReviewMarkRead(BaseModel):
    """Body of POST /planner-review/read. The client names the week it actually
    read rather than the server assuming "the latest": a tab left open across the
    Sunday-night beat would otherwise mark the NEW review read without anyone
    having seen it, and its banner would never appear."""

    week_start: str  # ISO date (Monday, settings.timezone)

    @field_validator("week_start")
    @classmethod
    def _valid_week_start(cls, v: str) -> str:
        try:
            date.fromisoformat(v)
        except ValueError as exc:
            raise ValueError("week_start must be an ISO date (YYYY-MM-DD)") from exc
        return v

"""
Application tracker routes.

Contract:
  GET    /api/app/applications                              -> ApplicationList
  POST   /api/app/applications                              -> ApplicationRead (201)
  GET    /api/app/applications/summary                      -> ApplicationSummary
  GET    /api/app/applications/funnel                       -> FunnelResponse
  GET    /api/app/applications/{application_id}             -> ApplicationDetail
  PATCH  /api/app/applications/{application_id}             -> ApplicationRead
  DELETE /api/app/applications/{application_id}             -> 204 (planned only)
  POST   /api/app/applications/{application_id}/transition  -> ApplicationRead
  POST   /api/app/applications/{application_id}/events      -> ApplicationEventRead (201)
  POST   /api/app/actions                                   -> ActionRead (201)
  GET    /api/app/actions[?due_on_or_before=|?scheduled_from=&scheduled_to=|?unscheduled=]
                                                            -> ActionList
  PATCH  /api/app/actions/{action_id}                       -> ActionRead
  GET    /api/app/planner-settings                          -> PlannerSettings
  PUT    /api/app/planner-settings                          -> PlannerSettings
  GET    /api/app/planner-stats?week=                       -> PlannerStats
  GET    /api/app/planner-review                            -> WeeklyReviewRead | null
  POST   /api/app/planner-review/read                       -> WeeklyReviewRead
  GET    /api/app/planner-day                               -> PlannerDayRead
  POST   /api/app/planner-day/commit                        -> PlannerDayLogRead
  POST   /api/app/planner-day/close                         -> PlannerDayLogRead

Every endpoint is workspace-scoped via get_current_workspace. Every by-id fetch
is verified against workspace.id (IDOR guard → 404 on miss/foreign). A body
job_id is scoped through its discovering run (global resource); a body profile_id
(workspace-private) is ownership-checked → 403.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.api.dependencies.auth import get_current_workspace
from apps.api.dependencies.db import get_db
from packages.contracts.api.applications import (
    ActionCreate,
    ActionList,
    ActionRead,
    ActionUpdate,
    ApplicationCreate,
    ApplicationDetail,
    ApplicationEventCreate,
    ApplicationEventRead,
    ApplicationJobRef,
    ApplicationList,
    ApplicationRead,
    ApplicationSummary,
    ApplicationUpdate,
    FunnelResponse,
    PlannerDayClose,
    PlannerDayCommit,
    PlannerDayLogRead,
    PlannerDayRead,
    PlannerSettings,
    PlannerSettingsUpdate,
    PlannerStats,
    PlannerWeek,
    StatusTransition,
    WeeklyReviewMarkRead,
    WeeklyReviewRead,
    WeeklyReviewStats,
)
from packages.domain.applications.transitions import (
    ACTIVE_STATUSES,
    PLANNED_STATUSES,
    InvalidTransition,
)
from packages.domain.planner.settings import load_planner_settings
from packages.infrastructure.db.models import (
    ApplicationAction,
    Job,
    JobApplication,
    PlannerDayLog,
    PlannerReview,
    Workspace,
)
from packages.infrastructure.db.repositories import (
    ApplicationActionRepository,
    ApplicationEventRepository,
    FitReportRepository,
    JobApplicationRepository,
    JobRepository,
    PlannerDayLogRepository,
    PlannerReviewRepository,
    ProfileRepository,
    RunRepository,
    WorkspaceRepository,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/app", tags=["applications"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _int_or_none(value: object) -> Optional[int]:
    """Read an integer out of an event payload, or nothing.

    A payload is whatever was written into JSON, and rows predating a field have
    no key at all. A malformed value must degrade to "unknown" rather than 500
    the week endpoint — the same reason ActionRead validates its payload in
    before-mode. bool is excluded explicitly: it is a subclass of int, and
    `True` minutes is not a duration.
    """
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _assert_owned(app: Optional[JobApplication], workspace: Workspace) -> JobApplication:
    """404 (enumeration-safe) if the application is missing or not in this workspace."""
    if app is None or app.workspace_id != workspace.id:
        raise HTTPException(status_code=404, detail="Application not found.")
    return app


def _job_in_workspace(db: Session, workspace: Workspace, job_id: str) -> Job:
    """A job is a global resource; ownership is proven transitively through the
    run that discovered/imported it. 404 (not 403) so a caller can't enumerate
    job ids from other workspaces — including private manual_paste jobs."""
    job = JobRepository(db).get(job_id)
    if job is None or not job.discovered_run_id:
        raise HTTPException(status_code=404, detail="Job not found.")
    run = RunRepository(db).get(job.discovered_run_id)
    if run is None or run.workspace_id != workspace.id:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job


def _assert_profile_owned(db: Session, workspace: Workspace, profile_id: str) -> None:
    profile = ProfileRepository(db).get_by_id(profile_id)
    if profile is None or profile.workspace_id != workspace.id:
        raise HTTPException(
            status_code=403, detail="profile_id does not belong to this workspace."
        )


def _application_read(
    app: JobApplication,
    *,
    job: Optional[Job] = None,
    next_action_due_at: Optional[datetime] = None,
    next_action_type: Optional[str] = None,
    fit_score: Optional[int] = None,
) -> ApplicationRead:
    return ApplicationRead(
        id=app.id,
        job_id=app.job_id,
        profile_id=app.profile_id,
        status=app.status,
        lane=app.lane,
        excitement=app.excitement,
        channel=app.channel,
        applied_at=app.applied_at,
        resume_run_id=app.resume_run_id,
        contact_name=app.contact_name,
        contact_note=app.contact_note,
        notes=app.notes,
        closed_reason=app.closed_reason,
        created_at=app.created_at,
        updated_at=app.updated_at,
        job=ApplicationJobRef.model_validate(job) if job is not None else None,
        next_action_due_at=next_action_due_at,
        next_action_type=next_action_type,
        fit_score=fit_score,
    )


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------


@router.get("/applications", response_model=ApplicationList)
def list_applications(
    status_group: Optional[str] = Query(None, description="planned | active | closed"),
    needs_action: bool = Query(False, description="Only applications with a due pending action"),
    include_fit: bool = Query(False, description="Populate fit_score per row (one batched query — for the planned queue)"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
) -> ApplicationList:
    repo = JobApplicationRepository(db)
    apps = repo.list_for_workspace(
        workspace.id,
        status_group=status_group,
        needs_action=needs_action,
        limit=limit,
        offset=offset,
    )
    # Job join + next-due batched (next-due in one query; jobs cached by id —
    # bounded N+1 acceptable at P0 scale, revisit if lists grow).
    job_repo = JobRepository(db)
    job_cache: dict[str, Optional[Job]] = {}
    for a in apps:
        if a.job_id not in job_cache:
            job_cache[a.job_id] = job_repo.get(a.job_id)
    action_map = ApplicationActionRepository(db).earliest_pending_action_map(
        workspace.id, [a.id for a in apps]
    )
    # Opt-in fit: one batched query for all rows (never per-row).
    fit_map = (
        FitReportRepository(db).latest_score_map(workspace.id, [a.job_id for a in apps])
        if include_fit else {}
    )
    items = []
    for a in apps:
        due_type = action_map.get(a.id)
        items.append(
            _application_read(
                a,
                job=job_cache.get(a.job_id),
                next_action_due_at=due_type[0] if due_type else None,
                next_action_type=due_type[1] if due_type else None,
                fit_score=fit_map.get(a.job_id),
            )
        )
    # total = page count at P0 (true paginated total is a P1 refinement).
    return ApplicationList(items=items, total=len(items))


@router.post("/applications", response_model=ApplicationRead, status_code=201)
def create_application(
    body: ApplicationCreate,
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
) -> ApplicationRead:
    job = _job_in_workspace(db, workspace, body.job_id)
    if body.profile_id is not None:
        _assert_profile_owned(db, workspace, body.profile_id)

    repo = JobApplicationRepository(db)

    def _conflict() -> HTTPException:
        existing = repo.get_by_job(workspace.id, body.job_id)
        return HTTPException(
            status_code=409,
            detail={
                "message": "An application already exists for this job.",
                "existing_application_id": existing.id if existing else None,
            },
        )

    if repo.get_by_job(workspace.id, body.job_id) is not None:
        raise _conflict()

    try:
        app = repo.create(
            workspace_id=workspace.id,
            job_id=body.job_id,
            status=body.status,
            channel=body.channel,
            lane=body.lane,
            excitement=body.excitement,
            applied_at=body.applied_at,
            profile_id=body.profile_id,
            resume_run_id=body.resume_run_id,
            contact_name=body.contact_name,
            contact_note=body.contact_note,
            notes=body.notes,
        )
        # Created directly as "applied" with no explicit date → stamp now (parity
        # with transition_status stamping applied_at on first reach of "applied").
        if app.status == "applied" and app.applied_at is None:
            app.applied_at = datetime.now(timezone.utc)
            db.flush()
        db.commit()
    except IntegrityError:
        # Lost a create race with a concurrent duplicate submit (the pre-check
        # passed for both). The unique (workspace_id, job_id) constraint rejected
        # the second write — converge on the same clean 409 as the pre-check.
        db.rollback()
        raise _conflict()
    return _application_read(app, job=job)


@router.get("/applications/summary", response_model=ApplicationSummary)
def get_applications_summary(
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
) -> ApplicationSummary:
    app_repo = JobApplicationRepository(db)
    by_status = app_repo.count_by_status(workspace.id)
    active = sum(v for k, v in by_status.items() if k in ACTIVE_STATUSES)
    planned = sum(v for k, v in by_status.items() if k in PLANNED_STATUSES)
    today_due = ApplicationActionRepository(db).count_due(
        workspace.id, datetime.now(timezone.utc)
    )
    needs_action = len(
        app_repo.list_for_workspace(workspace.id, needs_action=True, limit=1000)
    )
    return ApplicationSummary(
        today_due=today_due,
        active=active,
        planned=planned,
        needs_action=needs_action,
        by_status=by_status,
    )


@router.get("/applications/funnel", response_model=FunnelResponse)
def get_funnel(
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
) -> FunnelResponse:
    """Pipeline stages + advisory alerts for the Plan view's Pipeline zone.
    (Declared before /{application_id} so 'funnel' isn't captured as an id.)"""
    from packages.domain.planner.funnel import build_funnel
    from packages.infrastructure.planner_mapping import application_view

    app_repo = JobApplicationRepository(db)
    event_repo = ApplicationEventRepository(db)
    views = [
        application_view(a, event_repo.list_for_application(a.id, workspace.id), [])
        for a in app_repo.list_for_workspace(workspace.id, limit=10_000)
    ]
    result = build_funnel(
        views, load_planner_settings(workspace), datetime.now(timezone.utc)
    )
    return FunnelResponse(**result)


@router.get("/applications/{application_id}", response_model=ApplicationDetail)
def get_application(
    application_id: str,
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
) -> ApplicationDetail:
    repo = JobApplicationRepository(db)
    app = _assert_owned(repo.get(application_id, workspace.id), workspace)
    job = JobRepository(db).get(app.job_id)
    events = ApplicationEventRepository(db).list_for_application(app.id, workspace.id)
    actions = ApplicationActionRepository(db).list_for_application(app.id, workspace.id)
    fit = FitReportRepository(db).get_latest_for_job(
        workspace_id=workspace.id, job_id=app.job_id, profile_id=app.profile_id
    )
    base = _application_read(app, job=job, fit_score=fit.overall_match_score if fit else None)
    return ApplicationDetail(
        **base.model_dump(),
        events=events,
        actions=actions,
        fit_report_id=fit.id if fit else None,
    )


@router.patch("/applications/{application_id}", response_model=ApplicationRead)
def update_application(
    application_id: str,
    body: ApplicationUpdate,
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
) -> ApplicationRead:
    repo = JobApplicationRepository(db)
    _assert_owned(repo.get(application_id, workspace.id), workspace)
    if body.profile_id is not None:
        _assert_profile_owned(db, workspace, body.profile_id)
    app = repo.update_fields(
        application_id, workspace.id, **body.model_dump(exclude_unset=True)
    )
    db.commit()
    job = JobRepository(db).get(app.job_id)
    return _application_read(app, job=job)


@router.delete("/applications/{application_id}", status_code=204)
def delete_application(
    application_id: str,
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
) -> None:
    """Remove a never-applied application. 409 once it has any history.

    Deleting is for mistakes — a wrong URL, a duplicate, a row typed to try the
    box — and those are always still `planned`. An application that has been
    applied to is counted by the funnel, the interview rate and the already
    frozen weekly snapshots; erasing one would move numbers the user reads to
    judge the search, with nothing left to point at. Those close out instead.
    """
    repo = JobApplicationRepository(db)
    app = _assert_owned(repo.get(application_id, workspace.id), workspace)
    if app.status != "planned":
        raise HTTPException(
            status_code=409,
            detail="Only a planned application can be removed — close it out instead.",
        )
    repo.delete_planned(application_id, workspace.id)
    db.commit()


@router.post("/applications/{application_id}/transition", response_model=ApplicationRead)
def transition_application(
    application_id: str,
    body: StatusTransition,
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
) -> ApplicationRead:
    repo = JobApplicationRepository(db)
    _assert_owned(repo.get(application_id, workspace.id), workspace)
    try:
        app = repo.transition_status(
            application_id, workspace.id, body.status, note=body.note, force=body.force
        )
    except InvalidTransition as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    job = JobRepository(db).get(app.job_id)
    return _application_read(app, job=job)


@router.post(
    "/applications/{application_id}/events",
    response_model=ApplicationEventRead,
    status_code=201,
)
def add_application_event(
    application_id: str,
    body: ApplicationEventCreate,
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
) -> ApplicationEventRead:
    """Append a timeline event. event_type is whitelisted to note |
    interview_scheduled (the enum rejects a forged status_changed); cross-field
    requirements are checked here."""
    repo = JobApplicationRepository(db)
    _assert_owned(repo.get(application_id, workspace.id), workspace)
    event_repo = ApplicationEventRepository(db)
    if body.event_type == "note":
        if not body.message or not body.message.strip():
            raise HTTPException(status_code=422, detail="A note requires a message.")
        event = event_repo.append(
            application_id=application_id,
            workspace_id=workspace.id,
            event_type="note",
            message=body.message,
        )
    else:  # interview_scheduled — round (payload) drives thank_you/check_in
        if body.round_type is None or body.at is None:
            raise HTTPException(
                status_code=422, detail="An interview requires round_type and at."
            )
        event = event_repo.append(
            application_id=application_id,
            workspace_id=workspace.id,
            event_type="interview_scheduled",
            message=body.message,
            payload_json={
                "round_type": body.round_type,
                "at": body.at.isoformat(),
                "duration_minutes": body.duration_minutes,
            },
        )
    db.commit()
    return ApplicationEventRead.model_validate(event)


# ---------------------------------------------------------------------------
# Actions (planner "Today" queue)
# ---------------------------------------------------------------------------


@router.post("/actions", response_model=ActionRead, status_code=201)
def create_action(
    body: ActionCreate,
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
) -> ActionRead:
    if body.application_id is not None:
        _assert_owned(
            JobApplicationRepository(db).get(body.application_id, workspace.id), workspace
        )
    action = ApplicationActionRepository(db).create(
        workspace_id=workspace.id,
        type=body.type,
        title=body.title,
        application_id=body.application_id,
        due_at=body.due_at,
        auto_generated=False,
        est_minutes=body.est_minutes,
    )
    db.commit()
    return ActionRead.model_validate(action)


@router.get("/actions", response_model=ActionList)
def list_actions(
    due_on_or_before: Optional[datetime] = Query(
        None, description="Default: now — the Today view's cutoff"
    ),
    include_undated: bool = Query(True),
    scheduled_from: Optional[datetime] = Query(
        None, description="With scheduled_to: blocks placed in [from, to). Week grid."
    ),
    scheduled_to: Optional[datetime] = Query(None),
    unscheduled: bool = Query(
        False, description="Pending to-dos with no calendar slot yet — the week grid's tray."
    ),
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
) -> ActionList:
    """Three mutually exclusive selections over the same rows.

    Combining them is rejected rather than resolved by precedence: a caller that
    sends both a due cutoff and a scheduled range has two different questions in
    mind, and silently answering one of them is how a view ends up rendering
    numbers nobody asked for.
    """
    repo = ApplicationActionRepository(db)
    ranged = scheduled_from is not None or scheduled_to is not None
    if unscheduled and ranged:
        raise HTTPException(
            status_code=422, detail="unscheduled and scheduled_from/to are exclusive."
        )
    if (unscheduled or ranged) and due_on_or_before is not None:
        raise HTTPException(
            status_code=422,
            detail="due_on_or_before cannot be combined with the schedule filters.",
        )
    if unscheduled:
        actions = repo.list_unscheduled(workspace.id)
    elif ranged:
        if scheduled_from is None or scheduled_to is None:
            raise HTTPException(
                status_code=422,
                detail="scheduled_from and scheduled_to must be given together.",
            )
        actions = repo.list_scheduled_between(workspace.id, scheduled_from, scheduled_to)
    else:
        on_or_before = due_on_or_before or datetime.now(timezone.utc)
        actions = repo.list_due(
            workspace.id, on_or_before, include_undated=include_undated
        )
    return ActionList(items=actions, total=len(actions))


# Which statuses each op will act on. Absent = unrestricted (reopen carries its
# own undo window; schedule states its own rule below; unschedule only clears a
# calendar slot and revives nothing).
#
# The status that matters is "cancelled": the system retires a to-do when its
# application closes, and nothing retires it a second time — so a client holding
# a stale row could snooze one back to "pending" and leave a live to-do on Today
# for a closed application, permanently. A dropped application's panel is
# exactly that client. "done" and "dismissed" are here for the same reason in
# the other direction: the way back from done is `reopen`, which restores an
# undated to-do and clears completed_at, none of which a snooze can do.
#
# Same-status repeats stay allowed, because they are not revivals: complete() is
# deliberately idempotent for two tabs and a retried PATCH, and dismissing an
# already-dismissed row asks for nothing new.
_ACTIONABLE_FROM: dict[str, frozenset[str]] = {
    "complete": frozenset({"pending", "done"}),
    "snooze": frozenset({"pending"}),
    "dismiss": frozenset({"pending", "dismissed"}),
}
_PAST_TENSE = {"complete": "completed", "snooze": "snoozed", "dismiss": "dismissed"}


@router.patch("/actions/{action_id}", response_model=ActionRead)
def update_action(
    action_id: str,
    body: ActionUpdate,
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
) -> ActionRead:
    repo = ApplicationActionRepository(db)
    row = repo.get(action_id, workspace.id)
    if row is None:
        raise HTTPException(status_code=404, detail="Action not found.")
    allowed = _ACTIONABLE_FROM.get(body.op)
    if allowed is not None and row.status not in allowed:
        raise HTTPException(
            status_code=409,
            detail=f"A {row.status} to-do cannot be {_PAST_TENSE[body.op]}.",
        )
    if body.op == "complete":
        action = repo.complete(action_id, workspace.id)
    elif body.op == "snooze":
        action = repo.snooze(
            action_id, workspace.id, days=body.snooze_days, until=body.snooze_until
        )
    elif body.op == "reopen":
        _assert_within_undo_window(db, workspace, row)
        action = repo.reopen(action_id, workspace.id)
    elif body.op == "schedule":
        if body.scheduled_at is None:
            raise HTTPException(
                status_code=422, detail="Scheduling a to-do requires scheduled_at."
            )
        if row.status != "pending":
            # Placing a finished or retired to-do on the calendar would put a
            # block on a day for work nobody is going to do, and the grid has no
            # way to say so.
            raise HTTPException(
                status_code=409,
                detail="Only a pending to-do can be scheduled.",
            )
        action = repo.schedule(action_id, workspace.id, body.scheduled_at)
    elif body.op == "unschedule":
        action = repo.unschedule(action_id, workspace.id)
    else:  # dismiss
        action = repo.dismiss(action_id, workspace.id)
    db.commit()
    return ActionRead.model_validate(action)


def _assert_within_undo_window(
    db: Session, workspace: Workspace, row: ApplicationAction
) -> None:
    """Undo is for today's mis-clicks, not for editing history.

    Every live surface recomputes on read — the triplet, the done bar, the
    capacity bar and the funnel all self-correct — so an undo needs no
    bookkeeping there. Two snapshots do NOT recompute: planner_day_logs.done_est
    is measured once at close time, and planner_reviews.stats_json is frozen by
    the Monday beat. Undoing a completion either of those has already counted
    would not correct a number, it would make a stored one wrong.

    So: only inside the current local day, and only while that day is still
    open. Checked server-side because "the client may not decide what day it is"
    is the rule this planner already runs on (V6-C5) — the toast's own gate is a
    courtesy, not the enforcement.
    """
    from packages.domain.planner.rules import local_day_start_utc, local_today

    if row.completed_at is None:
        return  # not a completion; repo.reopen is a no-op anyway
    today, settings = _local_today_for(workspace)
    completed_at = (
        row.completed_at
        if row.completed_at.tzinfo
        else row.completed_at.replace(tzinfo=timezone.utc)
    )
    if completed_at < local_day_start_utc(today, settings.timezone):
        raise HTTPException(
            status_code=409,
            detail="Only today's completions can be undone.",
        )
    log = PlannerDayLogRepository(db).get_for_date(workspace.id, today)
    if log is not None and log.done_est is not None:
        raise HTTPException(
            status_code=409,
            detail="Today is already closed; its totals have been recorded.",
        )
    # The weekly review is the other frozen snapshot, and "still inside today"
    # does not imply "not yet reviewed": the beat runs Monday 02:00 UTC, which
    # for any workspace west of UTC-2 is still local SUNDAY, and _week_start_for
    # anchors on (today - 1 day) so the frozen week INCLUDES that Sunday. A
    # completion made Sunday afternoon can therefore already be counted in
    # stats_json while it is still today.
    completed_local = local_today(completed_at, settings.timezone)
    week_start = completed_local - timedelta(days=completed_local.weekday())
    if PlannerReviewRepository(db).get_for_week(workspace.id, week_start) is not None:
        raise HTTPException(
            status_code=409,
            detail="That week's review has been generated; its totals have been recorded.",
        )


# ---------------------------------------------------------------------------
# Planner settings (read-only at P0; PUT lands in P1)
# ---------------------------------------------------------------------------


@router.get("/planner-settings", response_model=PlannerSettings)
def get_planner_settings(
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
) -> PlannerSettings:
    # Shared with the worker's rule generation so defaults never drift.
    return load_planner_settings(workspace)


@router.put("/planner-settings", response_model=PlannerSettings)
def update_planner_settings(
    body: PlannerSettingsUpdate,
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
) -> PlannerSettings:
    """Partial update: merge the set fields over the stored JSON, re-validate the
    whole result through PlannerSettings (bounds + timezone/weekday/date checks →
    422), then persist the validated blob. Returns the full effective settings."""
    stored = workspace.planner_settings_json or {}
    patch = body.model_dump(exclude_unset=True)
    merged = {**stored, **patch}
    try:
        validated = PlannerSettings(**merged)
    except ValidationError as exc:
        # Clean, JSON-safe 422 (pydantic's raw errors() can carry a non-
        # serializable ctx exception object).
        raise HTTPException(
            status_code=422,
            detail=[{"loc": e["loc"], "msg": e["msg"], "type": e["type"]} for e in exc.errors()],
        )
    WorkspaceRepository(db).set_planner_settings(workspace.id, validated.model_dump())
    db.commit()
    return validated


@router.get("/planner-week", response_model=PlannerWeek)
def get_planner_week(
    week: Optional[str] = Query(None, description="ISO date in the target week; default = this week"),
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
) -> PlannerWeek:
    """The week's shape for the Today card's strip: scheduled interviews and how
    much is due each day. Read-only.

    An interview's time lives in the event's payload (`at`), not in a column, so
    the rounds are filtered in Python; only those landing inside the week get
    their company resolved, which keeps that to a handful of lookups."""
    from packages.domain.planner.rules import effective_est_minutes, local_today
    from packages.domain.planner.week import (
        DueItem,
        InterviewSlot,
        ScheduledBlock,
        build_week,
        contains,
        due_query_start_utc,
        week_bounds_utc,
        week_start_for,
    )

    settings = load_planner_settings(workspace)
    tz = settings.timezone
    now = datetime.now(timezone.utc)
    if week:
        try:
            ref = date.fromisoformat(week)
        except ValueError:
            raise HTTPException(status_code=422, detail="week must be an ISO date (YYYY-MM-DD).")
    else:
        ref = local_today(now, tz)
    start_date = week_start_for(ref)
    start, end = week_bounds_utc(start_date, tz)

    event_repo = ApplicationEventRepository(db)
    app_repo = JobApplicationRepository(db)
    job_repo = JobRepository(db)

    slots: list[InterviewSlot] = []
    job_cache: dict[str, Optional[Job]] = {}
    for e in event_repo.list_by_type_for_workspace(workspace.id, "interview_scheduled"):
        raw = (e.payload_json or {}).get("at")
        if not isinstance(raw, str):
            continue  # an interview with no time can't sit on a day
        try:
            at = datetime.fromisoformat(raw)
        except ValueError:
            continue
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        if not (start <= at < end):
            continue
        app = app_repo.get(e.application_id, workspace.id)
        if app is None:
            continue
        if app.job_id not in job_cache:
            job_cache[app.job_id] = job_repo.get(app.job_id)
        job = job_cache[app.job_id]
        slots.append(
            InterviewSlot(
                application_id=e.application_id,
                company=job.company if job else "",
                at=at,
                round_type=(e.payload_json or {}).get("round_type"),
                duration_minutes=_int_or_none((e.payload_json or {}).get("duration_minutes")),
            )
        )

    action_repo = ApplicationActionRepository(db)
    # Overdue and undated work is attributed to today (matching the capacity
    # bar), so per-day counting starts at today for the current week — counting
    # it on its original day too would show two dots for one to-do.
    today = local_today(now, tz)
    due_from = due_query_start_utc(start_date, today, tz)
    due_items = [
        DueItem(at=a.due_at, type=a.type, est_minutes=a.est_minutes)
        for a in action_repo.list_due_between(workspace.id, due_from, end)
        if a.due_at is not None
    ]
    # One row set answers both "how many" and "how long", so the count and the
    # minutes cannot drift apart.
    carried_rows = (
        action_repo.list_pending_carried_into_today(workspace.id, due_from)
        if contains(start_date, today)
        else []
    )
    carried = len(carried_rows)
    carried_est = sum(effective_est_minutes(type_, est) for type_, est in carried_rows)
    placed = [
        ScheduledBlock(
            action_id=a.id,
            title=a.title,
            # Normalised like the interview path above: a SQLite round-trip
            # drops tzinfo, and a naive instant serialises without an offset —
            # the browser would then read it in ITS zone and draw the block on a
            # different day than the bucket it was filed under.
            at=a.scheduled_at if a.scheduled_at.tzinfo else a.scheduled_at.replace(tzinfo=timezone.utc),
            type=a.type,
            est_minutes=a.est_minutes,
            status=a.status,
        )
        # `start`, not `due_from`: due counting begins at today for the current
        # week (overdue work is owed today), but a block placed on Monday is a
        # fact about Monday and must stay there.
        for a in action_repo.list_scheduled_between(workspace.id, start, end)
        if a.scheduled_at is not None
    ]
    return PlannerWeek(
        **build_week(
            interviews=slots,
            due_items=due_items,
            settings=settings,
            now_utc=now,
            week_start=start_date,
            carried_into_today=carried,
            carried_est_minutes=carried_est,
            blocks=placed,
        )
    )


@router.get("/planner-stats", response_model=PlannerStats)
def get_planner_stats(
    week: Optional[str] = Query(None, description="ISO date in the target week; default = this week"),
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
) -> PlannerStats:
    """This-week triplet: applied / outreach(networking done) / follow_ups(done)
    vs the weekly targets. Week = Mon..Sun in settings.timezone."""
    from packages.domain.planner.rules import local_day_start_utc, local_today

    settings = load_planner_settings(workspace)
    tz = settings.timezone
    if week:
        try:
            ref = date.fromisoformat(week)
        except ValueError:
            raise HTTPException(status_code=422, detail="week must be an ISO date (YYYY-MM-DD).")
    else:
        ref = local_today(datetime.now(timezone.utc), tz)
    monday = ref - timedelta(days=ref.weekday())
    start = local_day_start_utc(monday, tz)
    end = local_day_start_utc(monday + timedelta(days=7), tz)

    app_repo = JobApplicationRepository(db)
    action_repo = ApplicationActionRepository(db)
    return PlannerStats(
        week_start=monday.isoformat(),
        applied=app_repo.count_applied_in_range(workspace.id, start, end),
        outreach=action_repo.count_completed_by_type_in_range(workspace.id, "networking", start, end),
        follow_ups=action_repo.count_completed_by_type_in_range(workspace.id, "follow_up", start, end),
        weekly_target=settings.weekly_target,
    )


def _day_log_read(row: PlannerDayLog) -> PlannerDayLogRead:
    return PlannerDayLogRead(
        local_date=row.local_date.isoformat(),
        committed_est=row.committed_est,
        done_est=row.done_est,
        reflection=row.reflection,
        closed_at=row.closed_at,
    )


def _local_today_for(workspace: Workspace) -> tuple[date, PlannerSettings]:
    """Today in the workspace's timezone, plus the settings it came from. The
    day rituals never take a date from the client — see PlannerDayCommit."""
    from packages.domain.planner.rules import local_today

    settings = load_planner_settings(workspace)
    return local_today(datetime.now(timezone.utc), settings.timezone), settings


@router.get("/planner-day", response_model=PlannerDayRead)
def get_planner_day(
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
) -> PlannerDayRead:
    """Today's planner state: the ritual record, plus what has actually been
    completed so far.

    `log` is null when the day has no row — the morning ritual has not run,
    which is what the banner keys off. The done totals are measured on every
    read rather than taken from the log, because the done bar shows them all
    day while the log's own done_est is not written until the evening close."""
    from packages.domain.planner.rules import local_day_start_utc

    today, settings = _local_today_for(workspace)
    start = local_day_start_utc(today, settings.timezone)
    end = local_day_start_utc(today + timedelta(days=1), settings.timezone)

    action_repo = ApplicationActionRepository(db)
    row = PlannerDayLogRepository(db).get_for_date(workspace.id, today)
    return PlannerDayRead(
        log=_day_log_read(row) if row is not None else None,
        done_count=action_repo.count_completed_in_range(workspace.id, start, end),
        done_est=action_repo.sum_est_completed_in_range(workspace.id, start, end),
    )


@router.post("/planner-day/commit", response_model=PlannerDayLogRead)
def commit_planner_day(
    body: PlannerDayCommit,
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
) -> PlannerDayLogRead:
    """Snapshot the morning commitment: the sum of the effective estimates of
    the to-dos the user kept.

    The total is computed here, from the same per-type fallback the Today view
    renders with, so the number filed is the number the user agreed to. Ids that
    are not this workspace's are ignored rather than rejected — the list can
    move under a ritual left open — which also makes the endpoint the wrong
    place to learn whether an id exists."""
    today, _ = _local_today_for(workspace)
    committed = ApplicationActionRepository(db).sum_est_for_ids(
        workspace.id, body.kept_action_ids
    )
    row = PlannerDayLogRepository(db).commit_day(
        workspace.id, today, committed_est=committed
    )
    return _day_log_read(row)


@router.post("/planner-day/close", response_model=PlannerDayLogRead)
def close_planner_day(
    body: PlannerDayClose,
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
) -> PlannerDayLogRead:
    """Close the day: measure what was actually completed during it and stamp
    the moment.

    done_est is measured server-side over the closed day's completed_at window,
    never taken from the client. Closing a day whose morning ritual never ran is
    allowed and leaves committed_est NULL — that is a true record of what
    happened, and inventing a commitment to compare against would be worse.

    The day is today unless the body echoes back yesterday, which is what a
    session running past midnight sends: at 00:30 the server's "today" is a day
    that has not started, and closing it would stamp the new day finished before
    it began. 422 for anything further out — the client is confirming a date it
    was shown, not choosing one."""
    from packages.domain.planner.rules import local_day_start_utc

    today, settings = _local_today_for(workspace)
    tz = settings.timezone

    closing = today
    if body.local_date is not None:
        asked = date.fromisoformat(body.local_date)
        if asked not in (today, today - timedelta(days=1)):
            raise HTTPException(
                status_code=422,
                detail="local_date must be today or yesterday in the workspace timezone.",
            )
        closing = asked

    start = local_day_start_utc(closing, tz)
    end = local_day_start_utc(closing + timedelta(days=1), tz)

    done = ApplicationActionRepository(db).sum_est_completed_in_range(
        workspace.id, start, end
    )
    row = PlannerDayLogRepository(db).close_day(
        workspace.id,
        closing,
        done_est=done,
        reflection=(body.reflection or "").strip() or None,
        now_utc=datetime.now(timezone.utc),
    )
    return _day_log_read(row)


@router.get("/planner-review", response_model=Optional[WeeklyReviewRead])
def get_planner_review(
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
) -> Optional[WeeklyReviewRead]:
    """The most recent weekly review for the Plan view's Review zone, or null
    (200) when none has been generated yet. Reviews are written by the weekly
    Celery beat; narrative_md is null when generation degraded to the
    number-only template (degraded == True → the card renders stats only)."""
    row = PlannerReviewRepository(db).get_latest(workspace.id)
    if row is None:
        return None
    return _review_read(row)


@router.post("/planner-review/read", response_model=WeeklyReviewRead)
def mark_planner_review_read(
    body: WeeklyReviewMarkRead,
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
) -> WeeklyReviewRead:
    """Mark one week's review as seen — what the Plan banner's "view" button
    calls. The body names the week so a tab left open across the Sunday beat
    cannot mark a review the user never saw. Idempotent: a repeat keeps the first
    read_at. 404 when this workspace has no review for that week (the same answer
    another workspace's week gets)."""
    row = PlannerReviewRepository(db).mark_read(
        workspace.id, date.fromisoformat(body.week_start), now_utc=datetime.now(timezone.utc)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="No review for that week.")
    return _review_read(row)


def _review_read(row: PlannerReview) -> WeeklyReviewRead:
    return WeeklyReviewRead(
        week_start=row.week_start.isoformat(),
        stats=WeeklyReviewStats(**row.stats_json),
        narrative_md=row.narrative_md,
        degraded=row.narrative_md is None,
        generated_at=row.created_at,
        read_at=row.read_at,
    )

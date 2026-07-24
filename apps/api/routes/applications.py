"""
Application tracker routes.

Contract:
  GET    /api/app/applications                              -> ApplicationList
  POST   /api/app/applications                              -> ApplicationRead (201)
  GET    /api/app/applications/summary                      -> ApplicationSummary
  GET    /api/app/applications/{application_id}             -> ApplicationDetail
  PATCH  /api/app/applications/{application_id}             -> ApplicationRead
  POST   /api/app/applications/{application_id}/transition  -> ApplicationRead
  POST   /api/app/actions                                   -> ActionRead (201)
  GET    /api/app/actions                                   -> ActionList
  PATCH  /api/app/actions/{action_id}                       -> ActionRead
  GET    /api/app/planner-settings                          -> PlannerSettings

Every endpoint is workspace-scoped via get_current_workspace. Every by-id fetch
is verified against workspace.id (IDOR guard → 404 on miss/foreign). A body
job_id is scoped through its discovering run (global resource); a body profile_id
(workspace-private) is ownership-checked → 403.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
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
    ApplicationJobRef,
    ApplicationList,
    ApplicationRead,
    ApplicationSummary,
    ApplicationUpdate,
    PlannerSettings,
    StatusTransition,
)
from packages.domain.applications.transitions import (
    ACTIVE_STATUSES,
    PLANNED_STATUSES,
    InvalidTransition,
)
from packages.infrastructure.db.models import Job, JobApplication, Workspace
from packages.infrastructure.db.repositories import (
    ApplicationActionRepository,
    ApplicationEventRepository,
    FitReportRepository,
    JobApplicationRepository,
    JobRepository,
    ProfileRepository,
    RunRepository,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/app", tags=["applications"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
    )


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------


@router.get("/applications", response_model=ApplicationList)
def list_applications(
    status_group: Optional[str] = Query(None, description="planned | active | closed"),
    needs_action: bool = Query(False, description="Only applications with a due pending action"),
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
    due_map = ApplicationActionRepository(db).earliest_pending_due_map(
        workspace.id, [a.id for a in apps]
    )
    items = [
        _application_read(a, job=job_cache.get(a.job_id), next_action_due_at=due_map.get(a.id))
        for a in apps
    ]
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
    base = _application_read(app, job=job)
    return ApplicationDetail(
        **base.model_dump(),
        events=events,
        actions=actions,
        fit_score=fit.overall_match_score if fit else None,
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
    )
    db.commit()
    return ActionRead.model_validate(action)


@router.get("/actions", response_model=ActionList)
def list_actions(
    due_on_or_before: Optional[datetime] = Query(
        None, description="Default: now — the Today view's cutoff"
    ),
    include_undated: bool = Query(True),
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
) -> ActionList:
    on_or_before = due_on_or_before or datetime.now(timezone.utc)
    actions = ApplicationActionRepository(db).list_due(
        workspace.id, on_or_before, include_undated=include_undated
    )
    return ActionList(items=actions, total=len(actions))


@router.patch("/actions/{action_id}", response_model=ActionRead)
def update_action(
    action_id: str,
    body: ActionUpdate,
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
) -> ActionRead:
    repo = ApplicationActionRepository(db)
    if repo.get(action_id, workspace.id) is None:
        raise HTTPException(status_code=404, detail="Action not found.")
    if body.op == "complete":
        action = repo.complete(action_id, workspace.id)
    elif body.op == "snooze":
        action = repo.snooze(action_id, workspace.id, days=body.snooze_days)
    else:  # dismiss
        action = repo.dismiss(action_id, workspace.id)
    db.commit()
    return ActionRead.model_validate(action)


# ---------------------------------------------------------------------------
# Planner settings (read-only at P0; PUT lands in P1)
# ---------------------------------------------------------------------------


@router.get("/planner-settings", response_model=PlannerSettings)
def get_planner_settings(
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
) -> PlannerSettings:
    stored = getattr(workspace, "planner_settings_json", None) or {}
    return PlannerSettings(**stored)

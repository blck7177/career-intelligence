"""
Runs API — create a run, read status, cancel.

Contract:
  POST   /api/app/runs                    → RunRead
  GET    /api/app/runs                    → RunList
  GET    /api/app/runs/{run_id}           → RunRead
  POST   /api/app/runs/{run_id}/cancel   → RunRead

Auth:
  All endpoints require a valid Clerk Bearer JWT.
  workspace_id is resolved server-side from the authenticated user — never from the request body.

Debug endpoints (tasks / events / agent-invocations) have been moved to
  /api/admin/runs/{run_id}/... (apps/api/routes/admin_runs.py).
"""

from __future__ import annotations

import logging
import uuid

from celery import Celery
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.api.dependencies.auth import get_current_workspace
from apps.api.dependencies.db import get_db
from packages.contracts.api.runs import (
    RunCreate,
    RunList,
    RunRead,
)
from packages.contracts.tasks.envelopes import TaskEnvelope
from packages.domain.quota.tiers import get_quota_rule
from packages.infrastructure.db.models import Workspace
from packages.infrastructure.db.repositories import (
    ProfileRepository,
    RunRepository,
    TaskRepository,
    WorkspaceRepository,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/app/runs", tags=["runs"])


def _get_celery() -> Celery:
    """Lazy import to avoid circular imports at module load time."""
    import os

    from celery import Celery as _Celery

    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    app = _Celery(broker=redis_url)
    return app


def _assert_run_owned(run, workspace: Workspace) -> None:
    """Raise 403 if the run does not belong to the current workspace."""
    if run.workspace_id != workspace.id:
        raise HTTPException(status_code=403, detail="Access denied.")


_TASK_TYPE_MAP: dict[str, str] = {
    "job_discovery": "agent.job_discovery",
    "job_research": "agent.job_research",
    "run_reflection": "agent.run_reflection",
    "job_report": "job_report",
    "fit_report": "fit_report",
    "profile_import": "profile_import",
    "resume_tailor": "resume_tailor",
}


@router.post("", response_model=RunRead, status_code=201)
def create_run(
    body: RunCreate,
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
) -> RunRead:
    """
    Create a run and enqueue its first task via Celery.
    workspace_id comes from the authenticated user's session — not from the request body.
    Returns run_id immediately — frontend polls for status.
    """
    run_repo = RunRepository(db)
    task_repo = TaskRepository(db)

    # Row-lock the workspace for the rest of this transaction so the quota
    # check (count_this_month_for_workspace) and the run insert below happen
    # atomically w.r.t. any other concurrent create_run for this workspace.
    # Without this, concurrent requests can all read the same under-limit
    # count before any of them commits — real-concurrency-tested and
    # confirmed exploitable (8 concurrent requests, quota room for 1, all 8
    # created). See
    # dev_note/career/phase20-launch-hardening/concurrency_test_0711/README.md
    WorkspaceRepository(db).get_for_update(workspace.id)

    task_type = _TASK_TYPE_MAP[body.run_type]

    # Cross-workspace reference checks. body.input_snapshot can carry a
    # client-supplied id pointing at another workspace's private resource
    # (a prior run, a candidate profile) — these are not global/shared data
    # like `jobs`/`job_reports`, so unlike job_id they must be verified to
    # belong to the calling workspace before use. Found via real-data
    # incident analysis, not a hypothetical: see
    # dev_note/career/phase20-launch-hardening/openclaw_http_migration_0712/README.md
    if body.run_type == "run_reflection":
        reflected_run_id = getattr(body.input_snapshot, "run_id", None)
        reflected_run = run_repo.get(reflected_run_id) if reflected_run_id else None
        if reflected_run is None or reflected_run.workspace_id != workspace.id:
            raise HTTPException(
                status_code=403,
                detail="run_id does not belong to this workspace.",
            )

    if body.run_type in ("job_discovery", "fit_report"):
        profile_id = getattr(body.input_snapshot, "profile_id", None)
        if profile_id:
            profile = ProfileRepository(db).get_by_id(profile_id)
            if profile is None or profile.workspace_id != workspace.id:
                raise HTTPException(
                    status_code=403,
                    detail="profile_id does not belong to this workspace.",
                )

    quota_rule = get_quota_rule(workspace.tier, body.run_type)
    if quota_rule is not None:
        search_depth = getattr(body.input_snapshot, "search_depth", None)
        if (
            search_depth is not None
            and quota_rule.allowed_search_depth is not None
            and search_depth not in quota_rule.allowed_search_depth
        ):
            raise HTTPException(
                status_code=403,
                detail=(
                    f"search_depth={search_depth!r} is not available on the "
                    f"{workspace.tier!r} tier. Allowed: {list(quota_rule.allowed_search_depth)}."
                ),
            )

        if quota_rule.monthly_limit is not None:
            used = run_repo.count_this_month_for_workspace(workspace.id, body.run_type)
            if used >= quota_rule.monthly_limit:
                raise HTTPException(
                    status_code=429,
                    detail=(
                        f"Monthly quota reached for {body.run_type} on the "
                        f"{workspace.tier!r} tier ({used}/{quota_rule.monthly_limit})."
                    ),
                )

    correlation_id = str(uuid.uuid4())

    try:
        run = run_repo.create(
            workspace_id=workspace.id,
            run_type=body.run_type,
            input_snapshot_json=body.input_snapshot.model_dump(mode="json"),
            correlation_id=correlation_id,
        )
    except IntegrityError:
        # uq_active_agent_run_per_workspace_type — a queued/running run of this
        # type already exists for this workspace (see migration x5y6z7a8b9c0).
        db.rollback()
        existing = run_repo.get_active_for_workspace(workspace.id, body.run_type)
        raise HTTPException(
            status_code=409,
            detail={
                "message": f"A {body.run_type} run is already in progress for this workspace.",
                "existing_run_id": existing.id if existing else None,
            },
        )

    idempotency_key = f"{task_type}:{workspace.id}:{run.id}"

    task = task_repo.create(
        run_id=run.id,
        workspace_id=workspace.id,
        task_type=task_type,
        idempotency_key=idempotency_key,
    )

    db.commit()

    from packages.domain.agent_jobs.routing import celery_queue_for_task_type  # noqa: PLC0415

    envelope = TaskEnvelope(
        task_id=task.id,
        run_id=run.id,
        workspace_id=workspace.id,
        task_type=task_type,
        idempotency_key=idempotency_key,
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
        logger.info(
            "Enqueued task %s for run %s (queue=%s)", task.id, run.id, celery_queue
        )
    except Exception as exc:
        logger.warning("Failed to enqueue task (Celery unreachable?): %s", exc)

    return RunRead.model_validate(run)


@router.get("", response_model=RunList)
def list_runs(
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
) -> RunList:
    run_repo = RunRepository(db)
    runs = run_repo.list_for_workspace(workspace.id)
    return RunList(items=[RunRead.model_validate(r) for r in runs], total=len(runs))


@router.get("/{run_id}", response_model=RunRead)
def get_run(
    run_id: str,
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
) -> RunRead:
    run = RunRepository(db).get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    _assert_run_owned(run, workspace)
    return RunRead.model_validate(run)


@router.get("/{run_id}/resume-draft")
def get_resume_draft(
    run_id: str,
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
):
    """Return the resume tailor draft for a completed resume_tailor run."""
    run = RunRepository(db).get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    _assert_run_owned(run, workspace)
    if run.run_type != "resume_tailor":
        raise HTTPException(status_code=400, detail="Not a resume_tailor run")
    if run.status != "succeeded":
        raise HTTPException(status_code=409, detail=f"Run not yet complete: {run.status}")
    summary = run.result_summary_json or {}
    draft = summary.get("draft", {})
    if not draft:
        raise HTTPException(status_code=404, detail="No draft found in run result")
    return draft


@router.post("/{run_id}/cancel", response_model=RunRead)
def cancel_run(
    run_id: str,
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
) -> RunRead:
    run_repo = RunRepository(db)
    run = run_repo.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    _assert_run_owned(run, workspace)
    if run.status in ("succeeded", "failed", "cancelled"):
        raise HTTPException(
            status_code=409, detail=f"Run already in terminal state: {run.status}"
        )
    run = run_repo.set_status(run_id, "cancelled")
    db.commit()
    return RunRead.model_validate(run)

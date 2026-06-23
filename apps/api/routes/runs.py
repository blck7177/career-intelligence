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
from sqlalchemy.orm import Session

from apps.api.dependencies.auth import get_current_workspace
from apps.api.dependencies.db import get_db
from packages.contracts.api.runs import (
    RunCreate,
    RunList,
    RunRead,
)
from packages.contracts.tasks.envelopes import TaskEnvelope
from packages.infrastructure.db.models import Workspace
from packages.infrastructure.db.repositories import (
    RunRepository,
    TaskRepository,
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

    correlation_id = str(uuid.uuid4())

    run = run_repo.create(
        workspace_id=workspace.id,
        run_type=body.run_type,
        input_snapshot_json=body.input_snapshot,
        correlation_id=correlation_id,
    )

    task_type_map = {
        "job_discovery": "agent.job_discovery",
        "job_research": "agent.job_research",
        "run_reflection": "agent.run_reflection",
        "job_report": "job_report",
        "fit_report": "fit_report",
    }
    task_type = task_type_map.get(body.run_type)
    if task_type is None:
        raise HTTPException(status_code=400, detail=f"Unknown run_type: {body.run_type!r}")

    idempotency_key = f"{task_type}:{workspace.id}:{run.id}"

    task = task_repo.create(
        run_id=run.id,
        workspace_id=workspace.id,
        task_type=task_type,
        idempotency_key=idempotency_key,
    )

    db.commit()

    from packages.domain.agent_jobs.routing import celery_queue_for_task_type

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

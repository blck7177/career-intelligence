"""
Runs API — create a run, read status, list events, list agent invocations.

Contract:
  POST   /api/runs                           → RunRead
  GET    /api/runs/{run_id}                  → RunRead
  GET    /api/runs                           → RunList
  GET    /api/runs/{run_id}/tasks            → list[TaskRead]
  GET    /api/runs/{run_id}/events           → list[TaskEventRead]
  GET    /api/runs/{run_id}/agent-invocations → list[AgentInvocationRead]
  POST   /api/runs/{run_id}/cancel          → RunRead
"""

from __future__ import annotations

import logging
import uuid

from celery import Celery
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from apps.api.dependencies.db import get_db
from packages.contracts.api.runs import (
    AgentInvocationRead,
    RunCreate,
    RunList,
    RunRead,
    TaskEventRead,
    TaskRead,
)
from packages.contracts.tasks.envelopes import TaskEnvelope
from packages.infrastructure.db.repositories import (
    AgentInvocationRepository,
    RunRepository,
    TaskEventRepository,
    TaskRepository,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/runs", tags=["runs"])


def _get_celery() -> Celery:
    """Lazy import to avoid circular imports at module load time."""
    import os

    from celery import Celery as _Celery

    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    app = _Celery(broker=redis_url)
    return app


@router.post("", response_model=RunRead, status_code=201)
def create_run(body: RunCreate, db: Session = Depends(get_db)) -> RunRead:
    """
    Create a run and enqueue its first task via Celery.
    Returns run_id immediately — frontend polls for status.
    """
    run_repo = RunRepository(db)
    task_repo = TaskRepository(db)

    correlation_id = str(uuid.uuid4())

    run = run_repo.create(
        workspace_id=body.workspace_id,
        run_type=body.run_type,
        input_snapshot_json=body.input_snapshot,
        correlation_id=correlation_id,
    )

    # Determine task_type from run_type
    task_type_map = {
        "job_discovery": "agent.job_discovery",
        "job_research": "agent.job_research",
        "run_reflection": "agent.run_reflection",
    }
    task_type = task_type_map.get(body.run_type)
    if task_type is None:
        raise HTTPException(status_code=400, detail=f"Unknown run_type: {body.run_type!r}")

    idempotency_key = f"{task_type}:{body.workspace_id}:{run.id}"

    task = task_repo.create(
        run_id=run.id,
        workspace_id=body.workspace_id,
        task_type=task_type,
        idempotency_key=idempotency_key,
    )

    db.commit()

    # Enqueue via Celery
    envelope = TaskEnvelope(
        task_id=task.id,
        run_id=run.id,
        workspace_id=body.workspace_id,
        task_type=task_type,
        idempotency_key=idempotency_key,
    )
    try:
        celery_app = _get_celery()
        celery_app.send_task(
            "apps.worker.tasks.execute_task",
            kwargs={"envelope": envelope.model_dump(mode="json")},
            queue="tasks",
        )
        logger.info("Enqueued task %s for run %s", task.id, run.id)
    except Exception as exc:
        logger.warning("Failed to enqueue task (Celery unreachable?): %s", exc)
        # Don't fail the request — the task is persisted; can be re-queued

    return RunRead.model_validate(run)


@router.get("", response_model=RunList)
def list_runs(workspace_id: str, db: Session = Depends(get_db)) -> RunList:
    run_repo = RunRepository(db)
    runs = run_repo.list_for_workspace(workspace_id)
    return RunList(items=[RunRead.model_validate(r) for r in runs], total=len(runs))


@router.get("/{run_id}", response_model=RunRead)
def get_run(run_id: str, db: Session = Depends(get_db)) -> RunRead:
    run = RunRepository(db).get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return RunRead.model_validate(run)


@router.get("/{run_id}/tasks", response_model=list[TaskRead])
def list_tasks(run_id: str, db: Session = Depends(get_db)) -> list[TaskRead]:
    tasks = TaskRepository(db).list_for_run(run_id)
    return [TaskRead.model_validate(t) for t in tasks]


@router.get("/{run_id}/events", response_model=list[TaskEventRead])
def list_events(run_id: str, db: Session = Depends(get_db)) -> list[TaskEventRead]:
    events = TaskEventRepository(db).list_for_run(run_id)
    return [TaskEventRead.model_validate(e) for e in events]


@router.get("/{run_id}/agent-invocations", response_model=list[AgentInvocationRead])
def list_agent_invocations(
    run_id: str, db: Session = Depends(get_db)
) -> list[AgentInvocationRead]:
    invocations = AgentInvocationRepository(db).list_for_run(run_id)
    return [AgentInvocationRead.model_validate(inv) for inv in invocations]


@router.post("/{run_id}/cancel", response_model=RunRead)
def cancel_run(run_id: str, db: Session = Depends(get_db)) -> RunRead:
    run_repo = RunRepository(db)
    run = run_repo.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status in ("succeeded", "failed", "cancelled"):
        raise HTTPException(
            status_code=409, detail=f"Run already in terminal state: {run.status}"
        )
    run = run_repo.set_status(run_id, "cancelled")
    db.commit()
    return RunRead.model_validate(run)

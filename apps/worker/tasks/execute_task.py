"""
Main Celery task: execute_task

Entry point for all task execution.
Routes to OPENCLAW or DETERMINISTIC handler based on task_type.

Flow:
  1. Deserialize TaskEnvelope
  2. Mark task as running in Postgres
  3. Route to appropriate handler
  4. Handler writes results → Postgres
  5. Mark task succeeded / failed / needs_review
"""

from __future__ import annotations

import logging

from apps.worker.celery_app import celery_app
from apps.worker.router import dispatch
from packages.contracts.tasks.envelopes import TaskEnvelope
from packages.domain.agent_jobs.routing import ExecutionMode
from packages.infrastructure.db.repositories import TaskEventRepository, TaskRepository
from packages.infrastructure.db.session import get_session

logger = logging.getLogger(__name__)


@celery_app.task(name="apps.worker.tasks.execute_task", bind=True, max_retries=2)
def execute_task(self, *, envelope: dict) -> dict:
    """
    Universal task executor.
    Receives a TaskEnvelope dict (only IDs — full payload is read from Postgres).
    """
    env = TaskEnvelope(**envelope)
    logger.info(
        "execute_task started: task_id=%s task_type=%s attempt=%d",
        env.task_id,
        env.task_type,
        env.attempt,
    )

    with get_session() as session:
        task_repo = TaskRepository(session)
        event_repo = TaskEventRepository(session)

        task_repo.mark_running(env.task_id)
        event_repo.append(
            task_id=env.task_id,
            run_id=env.run_id,
            event_type="task_claimed",
            message=f"Worker claimed task (attempt {env.attempt})",
        )

    mode = dispatch(env)

    try:
        if mode == ExecutionMode.OPENCLAW:
            result = _run_openclaw_task(env)
        else:
            result = _run_deterministic_task(env)
    except Exception as exc:
        logger.exception("Task failed: task_id=%s error=%s", env.task_id, exc)
        with get_session() as session:
            task_repo = TaskRepository(session)
            event_repo = TaskEventRepository(session)
            task_repo.mark_failed(
                env.task_id,
                error_code="TASK_EXCEPTION",
                error_message=str(exc)[:500],
            )
            event_repo.append(
                task_id=env.task_id,
                run_id=env.run_id,
                event_type="task_failed",
                message=str(exc)[:500],
            )
        raise self.retry(exc=exc, countdown=60)

    return result


def _run_openclaw_task(env: TaskEnvelope) -> dict:
    """
    Stub for Phase 4: full OpenClaw agent integration.
    Phase 1 stubs out the agent call — only marks task succeeded.
    Full implementation in Phase 4 (agent/openclaw adapter).
    """
    logger.info(
        "OPENCLAW task stub (Phase 4 pending): task_id=%s type=%s",
        env.task_id,
        env.task_type,
    )
    with get_session() as session:
        task_repo = TaskRepository(session)
        event_repo = TaskEventRepository(session)
        event_repo.append(
            task_id=env.task_id,
            run_id=env.run_id,
            event_type="agent_invocation_skipped",
            message="Phase 4 pending — agent runtime not yet wired",
        )
        task_repo.mark_succeeded(env.task_id)
    return {"status": "stub_ok", "task_id": env.task_id}


def _run_deterministic_task(env: TaskEnvelope) -> dict:
    """
    Stub for deterministic (non-agent) tasks.
    Phase 3 will add real handlers here.
    """
    logger.info(
        "DETERMINISTIC task stub (Phase 3 pending): task_id=%s type=%s",
        env.task_id,
        env.task_type,
    )
    with get_session() as session:
        task_repo = TaskRepository(session)
        event_repo = TaskEventRepository(session)
        event_repo.append(
            task_id=env.task_id,
            run_id=env.run_id,
            event_type="task_completed_stub",
            message="Phase 3 pending — deterministic handler not yet implemented",
        )
        task_repo.mark_succeeded(env.task_id)
    return {"status": "stub_ok", "task_id": env.task_id}

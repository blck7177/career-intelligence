"""
Main Celery task: execute_task

Universal entry point for all task execution.
Routes to handler based on ExecutionMode (OPENCLAW or DETERMINISTIC).

Flow:
  1. Deserialize TaskEnvelope (only IDs — full payload is in Postgres)
  2. Mark task as running in Postgres
  3. Route to appropriate handler
  4. Handler writes results → Postgres / artifact volume
  5. Handler marks task succeeded / failed / needs_review
"""

from __future__ import annotations

import logging

from apps.worker.celery_app import celery_app
from apps.worker.router import dispatch
from apps.worker.tasks.fit_report import handle_fit_report
from apps.worker.tasks.job_report import handle_job_report
from apps.worker.tasks.profile_import import handle_profile_import
from apps.worker.tasks.reflect_run import handle_reflect_run
from apps.worker.tasks.research_run import handle_research_run
from apps.worker.tasks.search_run import handle_search_run
from packages.contracts.tasks.envelopes import TaskEnvelope
from packages.domain.agent_jobs.routing import ExecutionMode
from packages.infrastructure.db.repositories import RunRepository, TaskEventRepository, TaskRepository
from packages.infrastructure.db.session import get_session
from packages.infrastructure.observability.logging import set_correlation_id

logger = logging.getLogger(__name__)

# Maps OPENCLAW task_type → handler function
_OPENCLAW_HANDLERS = {
    "agent.job_discovery": handle_search_run,
    "agent.job_research": handle_research_run,
    "agent.run_reflection": handle_reflect_run,
}

# Maps DETERMINISTIC task_type → handler function
_DETERMINISTIC_HANDLERS = {
    "job_report": handle_job_report,
    "fit_report": handle_fit_report,
    "profile_import": handle_profile_import,
}


@celery_app.task(name="apps.worker.tasks.execute_task", bind=True, max_retries=0)
def execute_task(self, *, envelope: dict) -> dict:
    """
    Universal task executor.
    Receives a TaskEnvelope dict (only IDs — full payload is read from Postgres).
    """
    env = TaskEnvelope(**envelope)
    # Restore correlation_id so all log lines from this task are traceable
    if env.correlation_id:
        set_correlation_id(env.correlation_id)

    logger.info(
        "execute_task started: task_id=%s task_type=%s attempt=%d",
        env.task_id,
        env.task_type,
        env.attempt,
    )

    with get_session() as session:
        task_repo = TaskRepository(session)
        run_repo = RunRepository(session)
        event_repo = TaskEventRepository(session)

        task_repo.mark_running(env.task_id)
        run_repo.set_status(env.run_id, "running")
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
        # Mark task and run as failed, then return without retrying.
        # Retrying after an explicit failure would create zombie runs where
        # the DB already shows "failed" but Celery re-executes the task.
        # Handlers are responsible for calling _mark_failed for expected
        # error cases; this catch handles unhandled/unexpected exceptions.
        logger.exception("Task raised unexpectedly: task_id=%s error=%s", env.task_id, exc)
        with get_session() as session:
            task_repo = TaskRepository(session)
            run_repo = RunRepository(session)
            event_repo = TaskEventRepository(session)
            task_repo.mark_failed(
                env.task_id,
                error_code="TASK_EXCEPTION",
                error_message=str(exc)[:500],
            )
            run_repo.set_status(env.run_id, "failed")
            event_repo.append(
                task_id=env.task_id,
                run_id=env.run_id,
                event_type="task_failed",
                message=str(exc)[:500],
            )
        return {"status": "failed", "task_id": env.task_id, "error": str(exc)[:200]}

    return result


def _run_openclaw_task(env: TaskEnvelope) -> dict:
    """
    Dispatch to the correct OPENCLAW handler by task_type.
    Each agent type has its own handler that knows its manifest contract.
    """
    handler = _OPENCLAW_HANDLERS.get(env.task_type)
    if handler is None:
        logger.error(
            "No OPENCLAW handler registered for task_type=%s", env.task_type
        )
        with get_session() as session:
            task_repo = TaskRepository(session)
            run_repo = RunRepository(session)
            event_repo = TaskEventRepository(session)
            task_repo.mark_failed(
                env.task_id,
                error_code="UNKNOWN_OPENCLAW_TASK_TYPE",
                error_message=f"No OPENCLAW handler for task_type={env.task_type!r}",
            )
            run_repo.set_status(env.run_id, "failed")
            event_repo.append(
                task_id=env.task_id,
                run_id=env.run_id,
                event_type="task_failed",
                message=f"No OPENCLAW handler for task_type={env.task_type!r}",
            )
        return {"status": "failed", "task_id": env.task_id}

    return handler(env)


def _run_deterministic_task(env: TaskEnvelope) -> dict:
    """
    Dispatch to a DETERMINISTIC handler by task_type.
    """
    handler = _DETERMINISTIC_HANDLERS.get(env.task_type)
    if handler is None:
        logger.error(
            "No deterministic handler registered for task_type=%s", env.task_type
        )
        with get_session() as session:
            task_repo = TaskRepository(session)
            run_repo = RunRepository(session)
            event_repo = TaskEventRepository(session)
            task_repo.mark_failed(
                env.task_id,
                error_code="UNKNOWN_TASK_TYPE",
                error_message=f"No handler for task_type={env.task_type!r}",
            )
            run_repo.set_status(env.run_id, "failed")
            event_repo.append(
                task_id=env.task_id,
                run_id=env.run_id,
                event_type="task_failed",
                message=f"No deterministic handler for task_type={env.task_type!r}",
            )
        return {"status": "failed", "task_id": env.task_id}

    return handler(env)

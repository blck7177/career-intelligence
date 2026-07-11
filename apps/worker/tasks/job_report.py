"""
Handler for job_report tasks.

Execution mode: DETERMINISTIC
Purpose: Generate a Job Intelligence Report for a given job record.

Input (from run.input_snapshot_json):
  { "job_id": str, "use_research": bool, "force_refresh": bool,
    "research_artifact_id": str | None }

Output:
  - job_report.md artifact (narrative)
  - job_report.json artifact (structured)
  - job_reports DB row
  - task marked succeeded
"""
from __future__ import annotations

import logging

from pydantic import ValidationError

from packages.contracts.api.runs import JobReportInput
from packages.contracts.tasks.envelopes import TaskEnvelope
from packages.infrastructure.db.repositories import (
    RunRepository,
    TaskEventRepository,
    TaskRepository,
)
from packages.infrastructure.db.session import get_session
from packages.infrastructure.services.job_report_service import create_job_report

logger = logging.getLogger(__name__)


def handle_job_report(env: TaskEnvelope) -> dict:
    """
    Entry point for job_report tasks.
    Called by execute_task when task_type == "job_report".
    """
    from packages.infrastructure.llm.usage_writer import set_llm_context
    set_llm_context(run_id=env.run_id, task_id=env.task_id,
                    workspace_id=env.workspace_id, call_site="job_report")

    logger.info("job_report: starting task_id=%s run_id=%s", env.task_id, env.run_id)

    with get_session() as session:
        run = RunRepository(session).get_or_raise(env.run_id)
        snap = run.input_snapshot_json or {}

    try:
        inp = JobReportInput.model_validate(snap)
    except ValidationError as exc:
        logger.error("job_report: invalid input_snapshot: %s", exc)
        _mark_failed(env, error_code="INVALID_INPUT",
                     message=f"Invalid job_report input_snapshot: {exc}")
        return {"status": "failed", "task_id": env.task_id}

    try:
        with get_session() as session:
            result = create_job_report(
                session=session,
                run_id=env.run_id,
                task_id=env.task_id,
                workspace_id=env.workspace_id,
                job_id=inp.job_id,
                use_research=inp.use_research,
                research_artifact_id=inp.research_artifact_id,
                force_refresh=inp.force_refresh,
            )
    except ValueError as exc:
        logger.warning("job_report: input error: %s", exc)
        _mark_failed(env, error_code="INVALID_JOB_INPUT", message=str(exc)[:500])
        return {"status": "failed", "task_id": env.task_id}
    except RuntimeError as exc:
        logger.exception("job_report: analysis failed: %s", exc)
        _mark_failed(env, error_code="ANALYSIS_FAILED", message=str(exc)[:500])
        return {"status": "failed", "task_id": env.task_id}

    with get_session() as session:
        task_repo = TaskRepository(session)
        event_repo = TaskEventRepository(session)
        run_repo = RunRepository(session)
        task_repo.mark_succeeded(env.task_id)
        run_repo.set_status(env.run_id, "succeeded")
        run_repo.set_result_summary(env.run_id, {
            "validation_status": "passed",
            "report_type": "job_report",
            "report_id": result["job_report_id"],
        })
        event_repo.append(
            task_id=env.task_id,
            run_id=env.run_id,
            event_type="task_succeeded",
            message=(
                f"Job Intelligence Report generated: "
                f"job_report_id={result['job_report_id']} "
                f"status={result['status']} "
                f"used_research={result['used_research']}"
            ),
            payload_json={
                "report_type": "job_report",
                "report_id": result["job_report_id"],
            },
        )

    logger.info("job_report: task_id=%s succeeded report_id=%s", env.task_id, result["job_report_id"])

    auto_fit_profile_id = snap.get("auto_fit_profile_id")
    if auto_fit_profile_id:
        _chain_fit_report(env, inp.job_id, result["job_report_id"], auto_fit_profile_id)

    return {
        "status": "succeeded",
        "task_id": env.task_id,
        "job_report_id": result["job_report_id"],
        "cache_status": result["status"],
    }


def _chain_fit_report(
    env: TaskEnvelope,
    job_id: str,
    job_report_id: str,
    profile_id: str,
) -> None:
    """Auto-create and enqueue a fit_report run after job_report completes."""
    import uuid as _uuid
    from packages.domain.agent_jobs.routing import celery_queue_for_task_type
    from packages.contracts.tasks.envelopes import TaskEnvelope as TE

    try:
        correlation_id = str(_uuid.uuid4())
        with get_session() as session:
            run_repo = RunRepository(session)
            task_repo = TaskRepository(session)

            run = run_repo.create(
                workspace_id=env.workspace_id,
                run_type="fit_report",
                input_snapshot_json={
                    "job_id": job_id,
                    "job_report_id": job_report_id,
                    "force_refresh": False,
                    "profile_id": profile_id,
                },
                correlation_id=correlation_id,
            )
            task = task_repo.create(
                run_id=run.id,
                workspace_id=env.workspace_id,
                task_type="fit_report",
                idempotency_key=f"fit_report:{env.workspace_id}:{run.id}",
            )
            run_id = run.id
            task_id = task.id
            session.commit()

        envelope = TE(
            task_id=task_id,
            run_id=run_id,
            workspace_id=env.workspace_id,
            task_type="fit_report",
            idempotency_key=f"fit_report:{env.workspace_id}:{run_id}",
            correlation_id=correlation_id,
        )
        celery_queue = celery_queue_for_task_type("fit_report")
        from apps.worker.celery_app import celery_app
        celery_app.send_task(
            "apps.worker.tasks.execute_task",
            kwargs={"envelope": envelope.model_dump(mode="json")},
            queue=celery_queue,
        )
        logger.info(
            "job_report: auto-chained fit_report run=%s for job=%s profile=%s",
            run_id, job_id, profile_id,
        )
    except Exception as exc:
        logger.error("job_report: failed to chain fit_report: %s", exc, exc_info=True)


def _mark_failed(env: TaskEnvelope, *, error_code: str, message: str) -> None:
    with get_session() as session:
        task_repo = TaskRepository(session)
        event_repo = TaskEventRepository(session)
        run_repo = RunRepository(session)
        task_repo.mark_failed(env.task_id, error_code=error_code, error_message=message)
        run_repo.set_status(env.run_id, "failed")
        event_repo.append(
            task_id=env.task_id,
            run_id=env.run_id,
            event_type="task_failed",
            message=message,
        )

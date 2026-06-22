"""
Handler for job_report tasks.

Execution mode: DETERMINISTIC
Purpose: Generate a Job Intelligence Report for a given job record.

Input (from run.input_snapshot_json):
  Formal path:  { "job_id": str, "use_research": bool, "force_refresh": bool,
                  "research_artifact_id": str | None }
  Smoke path:   { "job_snapshot": dict, "use_research": bool, "force_refresh": bool }

Output:
  - job_report.md artifact (narrative)
  - job_report.json artifact (structured)
  - job_reports DB row
  - task marked succeeded
"""
from __future__ import annotations

import logging

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
    logger.info("job_report: starting task_id=%s run_id=%s", env.task_id, env.run_id)

    with get_session() as session:
        run = RunRepository(session).get_or_raise(env.run_id)
        snap = run.input_snapshot_json or {}

    job_id = snap.get("job_id")
    job_snapshot = snap.get("job_snapshot")
    use_research = bool(snap.get("use_research", True))
    force_refresh = bool(snap.get("force_refresh", False))
    research_artifact_id = snap.get("research_artifact_id")

    if not job_id and not job_snapshot:
        _mark_failed(env, error_code="MISSING_JOB_INPUT",
                     message="input_snapshot must contain job_id or job_snapshot")
        return {"status": "failed", "task_id": env.task_id}

    try:
        with get_session() as session:
            result = create_job_report(
                session=session,
                run_id=env.run_id,
                task_id=env.task_id,
                workspace_id=env.workspace_id,
                job_id=job_id,
                job_snapshot=job_snapshot,
                use_research=use_research,
                research_artifact_id=research_artifact_id,
                force_refresh=force_refresh,
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
        task_repo.mark_succeeded(env.task_id)
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
        )

    logger.info("job_report: task_id=%s succeeded report_id=%s", env.task_id, result["job_report_id"])
    return {
        "status": "succeeded",
        "task_id": env.task_id,
        "job_report_id": result["job_report_id"],
        "cache_status": result["status"],
    }


def _mark_failed(env: TaskEnvelope, *, error_code: str, message: str) -> None:
    with get_session() as session:
        task_repo = TaskRepository(session)
        event_repo = TaskEventRepository(session)
        task_repo.mark_failed(env.task_id, error_code=error_code, error_message=message)
        event_repo.append(
            task_id=env.task_id,
            run_id=env.run_id,
            event_type="task_failed",
            message=message,
        )

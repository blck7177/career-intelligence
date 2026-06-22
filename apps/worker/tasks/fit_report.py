"""
Handler for fit_report tasks.

Execution mode: DETERMINISTIC
Purpose: Generate a workspace-private Candidate Fit Report.

Input (from run.input_snapshot_json):
  Formal path:  { "job_id": str, "candidate_profile_id": str,
                  "profile_snapshot": dict, "job_report_id": str | None,
                  "force_refresh": bool }
  Smoke path:   { "job_snapshot": dict, "profile_snapshot": dict,
                  "job_report_id": str | None }

Requires an active Job Intelligence Report for the job.
Fails with MISSING_JOB_REPORT if none found.

Output:
  - fit_report.md artifact (narrative)
  - fit_report.json artifact (structured)
  - fit_reports DB row
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
from packages.infrastructure.services.fit_report_service import create_fit_report

logger = logging.getLogger(__name__)


def handle_fit_report(env: TaskEnvelope) -> dict:
    """
    Entry point for fit_report tasks.
    Called by execute_task when task_type == "fit_report".
    """
    logger.info("fit_report: starting task_id=%s run_id=%s", env.task_id, env.run_id)

    with get_session() as session:
        run = RunRepository(session).get_or_raise(env.run_id)
        snap = run.input_snapshot_json or {}

    job_id = snap.get("job_id")
    job_snapshot = snap.get("job_snapshot")
    candidate_profile_id = snap.get("candidate_profile_id")
    profile_snapshot = snap.get("profile_snapshot")
    job_report_id = snap.get("job_report_id")
    force_refresh = bool(snap.get("force_refresh", False))

    if not job_id and not job_snapshot:
        _mark_failed(env, error_code="MISSING_JOB_INPUT",
                     message="input_snapshot must contain job_id or job_snapshot")
        return {"status": "failed", "task_id": env.task_id}

    if not profile_snapshot and not candidate_profile_id:
        _mark_failed(env, error_code="MISSING_PROFILE_INPUT",
                     message="input_snapshot must contain profile_snapshot or candidate_profile_id")
        return {"status": "failed", "task_id": env.task_id}

    try:
        with get_session() as session:
            result = create_fit_report(
                session=session,
                run_id=env.run_id,
                task_id=env.task_id,
                workspace_id=env.workspace_id,
                job_id=job_id,
                job_snapshot=job_snapshot,
                candidate_profile_id=candidate_profile_id,
                profile_snapshot=profile_snapshot,
                job_report_id=job_report_id,
                force_refresh=force_refresh,
            )
    except ValueError as exc:
        msg = str(exc)
        error_code = "MISSING_JOB_REPORT" if "MISSING_JOB_REPORT" in msg else "INVALID_FIT_INPUT"
        logger.warning("fit_report: input error [%s]: %s", error_code, msg)
        _mark_failed(env, error_code=error_code, message=msg[:500])
        return {"status": "failed", "task_id": env.task_id}
    except RuntimeError as exc:
        logger.exception("fit_report: generation failed: %s", exc)
        _mark_failed(env, error_code="GENERATION_FAILED", message=str(exc)[:500])
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
                f"Candidate Fit Report generated: "
                f"fit_report_id={result['fit_report_id']} "
                f"score={result['overall_match_score']} "
                f"status={result['status']}"
            ),
        )

    logger.info(
        "fit_report: task_id=%s succeeded fit_report_id=%s score=%d",
        env.task_id,
        result["fit_report_id"],
        result["overall_match_score"],
    )
    return {
        "status": "succeeded",
        "task_id": env.task_id,
        "fit_report_id": result["fit_report_id"],
        "overall_match_score": result["overall_match_score"],
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

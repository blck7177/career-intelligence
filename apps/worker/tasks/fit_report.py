"""
Handler for fit_report tasks.

Execution mode: DETERMINISTIC
Purpose: Generate a workspace-private Candidate Fit Report.

Input (from run.input_snapshot_json):
  { "job_id": str, "job_report_id": str | None, "force_refresh": bool }

  profile_snapshot is NO LONGER accepted from the frontend. The worker loads
  the workspace's CandidateProfile from the DB. Use GET /api/app/profile to
  view or edit the profile before generating a fit report.

Requires an active Job Intelligence Report for the job.
Fails with MISSING_JOB_REPORT if none found.
Fails with MISSING_PROFILE if the workspace has no candidate profile.

Output:
  - fit_report.md artifact (narrative)
  - fit_report.json artifact (structured)
  - fit_reports DB row
  - task marked succeeded
"""
from __future__ import annotations

import logging

from pydantic import ValidationError

from packages.contracts.api.runs import FitReportInput
from packages.contracts.tasks.envelopes import TaskEnvelope
from packages.infrastructure.db.repositories import (
    ProfileRepository,
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

    try:
        inp = FitReportInput.model_validate(snap)
    except ValidationError as exc:
        logger.error("fit_report: invalid input_snapshot: %s", exc)
        _mark_failed(
            env,
            error_code="INVALID_INPUT",
            message=f"Invalid fit_report input_snapshot: {exc}",
        )
        return {"status": "failed", "task_id": env.task_id}

    # Load workspace profile from DB (profile data no longer comes from frontend).
    # Extract all attributes inside the session to avoid DetachedInstanceError.
    profile_snapshot = None
    profile_row_id = None
    with get_session() as session:
        profile_row = ProfileRepository(session).get_for_workspace(env.workspace_id)
        if profile_row is not None:
            profile_row_id = profile_row.id
            profile_snapshot = {
                "id": profile_row.id,
                "years_experience": profile_row.years_experience,
                "summary": profile_row.summary or "",
                "subject_areas": profile_row.subject_areas or [],
                "technical_skills": profile_row.technical_skills or [],
                "tools": profile_row.tools or [],
                "representative_projects": profile_row.representative_projects or [],
            }

    if profile_snapshot is None:
        _mark_failed(
            env,
            error_code="MISSING_PROFILE",
            message=(
                "No candidate profile found for this workspace. "
                "Visit /profile to set up your profile before generating a fit report."
            ),
        )
        return {"status": "failed", "task_id": env.task_id}

    try:
        with get_session() as session:
            result = create_fit_report(
                session=session,
                run_id=env.run_id,
                task_id=env.task_id,
                workspace_id=env.workspace_id,
                job_id=job_id,
                candidate_profile_id=profile_row_id,
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
        run_repo = RunRepository(session)
        task_repo.mark_succeeded(env.task_id)
        run_repo.set_status(env.run_id, "succeeded")
        run_repo.set_result_summary(env.run_id, {
            "validation_status": "passed",
            "report_type": "fit_report",
            "report_id": result["fit_report_id"],
        })
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
            payload_json={
                "report_type": "fit_report",
                "report_id": result["fit_report_id"],
            },
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
        run_repo = RunRepository(session)
        task_repo.mark_failed(env.task_id, error_code=error_code, error_message=message)
        run_repo.set_status(env.run_id, "failed")
        event_repo.append(
            task_id=env.task_id,
            run_id=env.run_id,
            event_type="task_failed",
            message=message,
        )

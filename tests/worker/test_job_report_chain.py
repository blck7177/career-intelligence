"""
job_report → fit_report auto-chain hardening (punch-list G4 / B2).

Before: a job_report that failed inside a batch_analyze request silently dropped
the downstream fit_report — no trace, and the caller (which only sees the
job_report run ids synchronously) had no handle on the chained fit_report run.

After:
  - _chain_fit_report returns the created fit_report run_id (or None on failure)
  - handle_job_report records chained_fit_report_run_id in result_summary + event
  - _mark_failed emits a `fit_report_chain_skipped` event when the failed
    job_report was the first stage of an auto-chain
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from packages.contracts.tasks.envelopes import TaskEnvelope


def _env() -> TaskEnvelope:
    return TaskEnvelope(
        task_id="task-jr",
        run_id="run-jr",
        workspace_id="ws-1",
        task_type="job_report",
        idempotency_key="job_report:ws-1:run-jr",
        correlation_id="corr-1",
    )


class _SessionCtx:
    """Minimal get_session() context-manager stand-in wrapping a MagicMock session."""

    def __init__(self, session):
        self._session = session

    def __enter__(self):
        return self._session

    def __exit__(self, *a):
        return False


class TestChainReturnsRunId:
    def test_chain_returns_created_run_id(self):
        from apps.worker.tasks import job_report

        session = MagicMock()
        with (
            patch.object(job_report, "get_session", return_value=_SessionCtx(session)),
            patch.object(job_report, "RunRepository") as MockRun,
            patch.object(job_report, "TaskRepository") as MockTask,
            patch("apps.worker.celery_app.celery_app") as mock_celery,
            patch("packages.domain.agent_jobs.routing.celery_queue_for_task_type", return_value="fast"),
        ):
            MockRun.return_value.create.return_value = SimpleNamespace(id="fit-run-99")
            MockTask.return_value.create.return_value = SimpleNamespace(id="fit-task-99")

            run_id = job_report._chain_fit_report(_env(), "job-1", "jr-1", "profile-1")

        assert run_id == "fit-run-99"
        mock_celery.send_task.assert_called_once()

    def test_chain_returns_none_on_failure(self):
        from apps.worker.tasks import job_report

        session = MagicMock()
        with (
            patch.object(job_report, "get_session", return_value=_SessionCtx(session)),
            patch.object(job_report, "RunRepository") as MockRun,
        ):
            MockRun.return_value.create.side_effect = RuntimeError("db down")
            run_id = job_report._chain_fit_report(_env(), "job-1", "jr-1", "profile-1")

        assert run_id is None


class TestFailureNotifiesChainSkipped:
    def test_mark_failed_emits_chain_skipped_event_when_auto_fit_set(self):
        from apps.worker.tasks import job_report

        session = MagicMock()
        event_repo = MagicMock()
        with (
            patch.object(job_report, "get_session", return_value=_SessionCtx(session)),
            patch.object(job_report, "TaskRepository"),
            patch.object(job_report, "RunRepository"),
            patch.object(job_report, "TaskEventRepository", return_value=event_repo),
        ):
            job_report._mark_failed(
                _env(),
                error_code="ANALYSIS_FAILED",
                message="boom",
                chained_fit_skipped_profile_id="profile-1",
            )

        event_types = [c.kwargs.get("event_type") for c in event_repo.append.call_args_list]
        assert "fit_report_chain_skipped" in event_types
        # the skip event must carry the intended profile so it's actionable
        skip_call = next(
            c for c in event_repo.append.call_args_list
            if c.kwargs.get("event_type") == "fit_report_chain_skipped"
        )
        assert skip_call.kwargs["payload_json"]["intended_profile_id"] == "profile-1"

    def test_mark_failed_no_chain_event_when_not_auto_fit(self):
        from apps.worker.tasks import job_report

        session = MagicMock()
        event_repo = MagicMock()
        with (
            patch.object(job_report, "get_session", return_value=_SessionCtx(session)),
            patch.object(job_report, "TaskRepository"),
            patch.object(job_report, "RunRepository"),
            patch.object(job_report, "TaskEventRepository", return_value=event_repo),
        ):
            job_report._mark_failed(_env(), error_code="ANALYSIS_FAILED", message="boom")

        event_types = [c.kwargs.get("event_type") for c in event_repo.append.call_args_list]
        assert "fit_report_chain_skipped" not in event_types

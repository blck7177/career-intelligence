"""
Unit tests for the profile_import worker handler.

Tests the handler in isolation by mocking the DB session and LLM client.
No Docker, no Postgres, no Redis required.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from packages.contracts.api.profile_import import (
    CleanResume,
    ImportProject,
    ParseNotes,
    ProfileImportDraft,
)
from packages.contracts.tasks.envelopes import TaskEnvelope


def _make_envelope(**overrides) -> TaskEnvelope:
    defaults = {
        "task_id": "task-111",
        "run_id": "run-222",
        "workspace_id": "ws-333",
        "task_type": "profile_import",
        "idempotency_key": "profile_import:ws-333:run-222",
    }
    defaults.update(overrides)
    return TaskEnvelope(**defaults)


def _make_run(input_snapshot: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id="run-222",
        workspace_id="ws-333",
        run_type="profile_import",
        status="running",
        input_snapshot_json=input_snapshot,
    )


def _make_draft() -> ProfileImportDraft:
    return ProfileImportDraft(
        clean_resume=CleanResume(
            markdown="# John Doe\n\n## Experience\n\n### Risk Analyst — Big Bank\n2020–2024\n\n- VaR model validation\n- Python automation",
            experiences=[
                {"employer": "Big Bank", "title": "Risk Analyst", "start_date": "2020", "end_date": "2024", "bullets": ["VaR model validation", "Python automation"]},
            ],
            education=[
                {"institution": "Columbia University", "degree": "MS Financial Engineering", "graduation_date": "2020"},
            ],
            skills=[
                {"category": "Programming", "items": ["Python", "SQL", "R"]},
            ],
        ),
        summary="Risk analytics professional with 4 years experience.",
        experience_summary="Worked at Big Bank doing VaR validation.",
        education_summary="MS Financial Engineering, Columbia University",
        years_experience=4,
        technical_skills=["Python", "SQL", "R"],
        subject_areas=["market risk", "model validation", "VaR", "CCAR"],
        tools=["Python", "R", "Bloomberg"],
        representative_projects=[
            ImportProject(
                title="VaR Automation",
                description="Automated VaR backtesting pipeline",
                skills_used=["Python", "backtesting"],
                quantified_impact="Reduced cycle from 2 weeks to 3 days",
            ),
        ],
        parse_notes=ParseNotes(
            low_confidence_items=[],
            missing_information=["No salary expectation found"],
            assumptions=["Inferred 4 years from graduation date"],
        ),
    )


class TestProfileImportHandler:
    """Happy path and error cases for handle_profile_import."""

    @patch("apps.worker.tasks.profile_import.get_session")
    @patch("apps.worker.tasks.profile_import.get_llm_client")
    def test_happy_path(self, mock_get_llm, mock_get_session):
        """LLM returns valid draft → result_summary_json populated, task succeeded."""
        from apps.worker.tasks.profile_import import handle_profile_import

        env = _make_envelope()
        resume = "John Doe — Risk Analyst at Big Bank, 4 years, Python, VaR."

        mock_llm = MagicMock()
        mock_llm.complete_structured.return_value = _make_draft()
        mock_get_llm.return_value = mock_llm

        mock_session = MagicMock()
        mock_run_repo = MagicMock()
        mock_task_repo = MagicMock()
        mock_event_repo = MagicMock()

        mock_run_repo.get_or_raise.return_value = _make_run(
            {"resume_text": resume, "source_type": "paste"}
        )

        call_count = 0

        def session_context():
            nonlocal call_count
            call_count += 1
            ctx = MagicMock()
            ctx.__enter__ = MagicMock(return_value=mock_session)
            ctx.__exit__ = MagicMock(return_value=False)
            return ctx

        mock_get_session.side_effect = session_context

        with patch("apps.worker.tasks.profile_import.RunRepository", return_value=mock_run_repo):
            with patch(
                "apps.worker.tasks.profile_import.TaskRepository",
                return_value=mock_task_repo,
            ):
                with patch(
                    "apps.worker.tasks.profile_import.TaskEventRepository",
                    return_value=mock_event_repo,
                ):
                    result = handle_profile_import(env)

        assert result["status"] == "succeeded"
        assert result["task_id"] == "task-111"

        mock_llm.complete_structured.assert_called_once()
        call_args = mock_llm.complete_structured.call_args
        assert "resume_text" in call_args.kwargs.get("user_prompt", call_args.args[1] if len(call_args.args) > 1 else "")

        mock_run_repo.complete.assert_called_once()
        summary = mock_run_repo.complete.call_args.kwargs.get(
            "result_summary",
            mock_run_repo.complete.call_args[1].get("result_summary") if len(mock_run_repo.complete.call_args) > 1 else None,
        )
        assert summary["validation_status"] == "passed"
        assert summary["import_type"] == "profile_import"

        # source_resume: deterministic metadata about the input
        assert summary["source_resume"]["source_type"] == "paste"
        assert summary["source_resume"]["raw_text"] == resume
        assert summary["source_resume"]["char_count"] == len(resume)

        # clean_resume: LLM-reconstructed faithful resume
        assert "markdown" in summary["clean_resume"]
        assert len(summary["clean_resume"]["experiences"]) > 0

        # profile_draft: synthesized profile (must NOT contain clean_resume)
        assert "summary" in summary["profile_draft"]
        assert "technical_skills" in summary["profile_draft"]
        assert "clean_resume" not in summary["profile_draft"]

        assert summary["parse_notes"]["assumptions"] == [
            "Inferred 4 years from graduation date"
        ]

        mock_task_repo.mark_succeeded.assert_called_once_with("task-111")

    @patch("apps.worker.tasks.profile_import.get_session")
    def test_missing_resume_text(self, mock_get_session):
        """Empty resume_text → task failed with MISSING_RESUME_TEXT."""
        from apps.worker.tasks.profile_import import handle_profile_import

        env = _make_envelope()

        mock_session = MagicMock()
        mock_run_repo = MagicMock()
        mock_task_repo = MagicMock()
        mock_event_repo = MagicMock()
        mock_run_repo_for_fail = MagicMock()

        mock_run_repo.get_or_raise.return_value = _make_run(
            {"resume_text": "", "source_type": "paste"}
        )

        calls = []

        def session_context():
            ctx = MagicMock()
            ctx.__enter__ = MagicMock(return_value=mock_session)
            ctx.__exit__ = MagicMock(return_value=False)
            calls.append(ctx)
            return ctx

        mock_get_session.side_effect = session_context

        with patch("apps.worker.tasks.profile_import.RunRepository", return_value=mock_run_repo):
            with patch(
                "apps.worker.tasks.profile_import.TaskRepository",
                return_value=mock_task_repo,
            ):
                with patch(
                    "apps.worker.tasks.profile_import.TaskEventRepository",
                    return_value=mock_event_repo,
                ):
                    result = handle_profile_import(env)

        assert result["status"] == "failed"
        mock_task_repo.mark_failed.assert_called_once()
        error_code = mock_task_repo.mark_failed.call_args[1].get(
            "error_code", mock_task_repo.mark_failed.call_args.kwargs.get("error_code")
        )
        assert error_code in ("MISSING_RESUME_TEXT", "INVALID_INPUT")
        mock_run_repo.set_status.assert_called_once_with("run-222", "failed")

    @patch("apps.worker.tasks.profile_import.get_session")
    def test_resume_too_long(self, mock_get_session):
        """Resume exceeding limit → task failed with RESUME_TOO_LONG."""
        from apps.worker.tasks.profile_import import handle_profile_import

        env = _make_envelope()

        mock_session = MagicMock()
        mock_run_repo = MagicMock()
        mock_task_repo = MagicMock()
        mock_event_repo = MagicMock()

        mock_run_repo.get_or_raise.return_value = _make_run(
            {"resume_text": "x" * 60_000, "source_type": "paste"}
        )

        def session_context():
            ctx = MagicMock()
            ctx.__enter__ = MagicMock(return_value=mock_session)
            ctx.__exit__ = MagicMock(return_value=False)
            return ctx

        mock_get_session.side_effect = session_context

        with patch("apps.worker.tasks.profile_import.RunRepository", return_value=mock_run_repo):
            with patch(
                "apps.worker.tasks.profile_import.TaskRepository",
                return_value=mock_task_repo,
            ):
                with patch(
                    "apps.worker.tasks.profile_import.TaskEventRepository",
                    return_value=mock_event_repo,
                ):
                    result = handle_profile_import(env)

        assert result["status"] == "failed"
        mock_task_repo.mark_failed.assert_called_once()
        error_code = mock_task_repo.mark_failed.call_args.kwargs.get("error_code")
        assert error_code in ("RESUME_TOO_LONG", "INVALID_INPUT")
        mock_run_repo.set_status.assert_called_once_with("run-222", "failed")

    @patch("apps.worker.tasks.profile_import.get_session")
    @patch("apps.worker.tasks.profile_import.get_llm_client")
    def test_llm_failure(self, mock_get_llm, mock_get_session):
        """LLM raises LLMCallError → task failed with GENERATION_FAILED."""
        from packages.infrastructure.llm.client import LLMCallError
        from apps.worker.tasks.profile_import import handle_profile_import

        env = _make_envelope()

        mock_llm = MagicMock()
        mock_llm.complete_structured.side_effect = LLMCallError("API timeout")
        mock_get_llm.return_value = mock_llm

        mock_session = MagicMock()
        mock_run_repo = MagicMock()
        mock_task_repo = MagicMock()
        mock_event_repo = MagicMock()

        mock_run_repo.get_or_raise.return_value = _make_run(
            {"resume_text": "Some valid resume text here.", "source_type": "paste"}
        )

        def session_context():
            ctx = MagicMock()
            ctx.__enter__ = MagicMock(return_value=mock_session)
            ctx.__exit__ = MagicMock(return_value=False)
            return ctx

        mock_get_session.side_effect = session_context

        with patch("apps.worker.tasks.profile_import.RunRepository", return_value=mock_run_repo):
            with patch(
                "apps.worker.tasks.profile_import.TaskRepository",
                return_value=mock_task_repo,
            ):
                with patch(
                    "apps.worker.tasks.profile_import.TaskEventRepository",
                    return_value=mock_event_repo,
                ):
                    result = handle_profile_import(env)

        assert result["status"] == "failed"
        mock_task_repo.mark_failed.assert_called_once()
        error_code = mock_task_repo.mark_failed.call_args.kwargs.get("error_code")
        assert error_code == "GENERATION_FAILED"
        mock_run_repo.set_status.assert_called_once_with("run-222", "failed")


class TestProfileImportDraftSchema:
    """Contract test: ProfileImportDraft fields must be a superset of editable profile fields."""

    def test_draft_covers_profile_update_fields(self):
        """Ensure ProfileImportDraft has all editable profile fields."""
        from apps.api.routes.profile import ProfileUpdate

        update_fields = set(ProfileUpdate.model_fields.keys())
        draft_fields = set(ProfileImportDraft.model_fields.keys())
        # draft-only: fields in draft that don't map to profile update
        draft_only = {"parse_notes", "clean_resume"}
        # update-only: user-set fields not extracted from resume
        update_only = {"label"}
        actual_missing = update_fields - draft_fields - draft_only - update_only
        assert actual_missing == set(), (
            f"ProfileImportDraft is missing fields from ProfileUpdate: "
            f"{actual_missing}"
        )

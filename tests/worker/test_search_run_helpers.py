"""
Unit tests for search_run helper functions.
No IO against real DB — repositories are mocked.

Covers:
  - _canonicalize_discovery_artifact_paths: platform-owned keys stripped from manifest
  - _mark_needs_review: result_summary_json is structured and contains expected fields
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from packages.contracts.agents.manifests import DiscoveryManifest
from packages.contracts.tasks.envelopes import TaskEnvelope


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_manifest(artifact_paths: dict | None = None) -> DiscoveryManifest:
    return DiscoveryManifest(
        invocation_id="ainv_test",
        status="completed",
        stop_reason="budget_exhausted",
        candidate_count=5,
        sources_tried=["linkedin", "indeed"],
        artifact_paths=artifact_paths or {},
    )


def make_envelope(run_id: str = "run_001", task_id: str = "task_001") -> TaskEnvelope:
    return TaskEnvelope(
        run_id=run_id,
        task_id=task_id,
        workspace_id="ws_001",
        task_type="agent.job_discovery",
        attempt=1,
        idempotency_key=f"{task_id}:attempt:1",
    )


def make_output_paths(base: str = "/tmp") -> MagicMock:
    """Minimal OutputPaths stand-in."""
    op = MagicMock()
    op.candidate_pool_path = f"{base}/candidate_pool.jsonl"
    op.search_ledger_path = f"{base}/search_ledger.jsonl"
    op.trace_events_path = f"{base}/trace_events.jsonl"
    op.coverage_report_path = f"{base}/coverage_report.md"
    op.output_manifest_path = f"{base}/output_manifest.json"
    op.tool_events_path = f"{base}/tool_events.jsonl"
    return op


# ---------------------------------------------------------------------------
# _canonicalize_discovery_artifact_paths — platform guard
# ---------------------------------------------------------------------------


class TestCanonicalize:
    """Tests for _canonicalize_discovery_artifact_paths helper."""

    def _run(self, manifest: DiscoveryManifest, output_paths, tmp_path: Path):
        from apps.worker.tasks.search_run import _canonicalize_discovery_artifact_paths

        manifest_path = tmp_path / "output_manifest.json"
        manifest_path.write_text(manifest.model_dump_json())
        _canonicalize_discovery_artifact_paths(manifest, output_paths, manifest_path)
        return manifest_path

    def test_platform_key_stripped_from_manifest(self, tmp_path):
        """Agent-reported tool_events key must be removed from manifest.artifact_paths."""
        manifest = make_manifest(
            {
                "candidate_pool": "/agent/candidate_pool.jsonl",
                "tool_events": "/agent/tool_events.jsonl",  # platform-owned — must be stripped
            }
        )
        op = make_output_paths(str(tmp_path))
        self._run(manifest, op, tmp_path)

        assert "tool_events" not in manifest.artifact_paths

    def test_platform_key_stripped_and_written_back_to_disk(self, tmp_path):
        """Manifest written back to disk must also not contain platform key."""
        manifest = make_manifest(
            {
                "candidate_pool": "/agent/candidate_pool.jsonl",
                "tool_events": "/agent/tool_events.jsonl",
            }
        )
        op = make_output_paths(str(tmp_path))
        manifest_path = self._run(manifest, op, tmp_path)

        on_disk = json.loads(manifest_path.read_text())
        assert "tool_events" not in on_disk.get("artifact_paths", {})

    def test_agent_reported_paths_are_canonicalized(self, tmp_path):
        """Agent-reported candidate_pool path is overwritten with platform path."""
        manifest = make_manifest(
            {"candidate_pool": "/agent-wrong/pool.jsonl"}
        )
        op = make_output_paths(str(tmp_path))
        self._run(manifest, op, tmp_path)

        assert manifest.artifact_paths["candidate_pool"] == op.candidate_pool_path

    def test_no_platform_key_no_change(self, tmp_path):
        """Manifest without tool_events key: canonicalize runs, tool_events stays absent."""
        manifest = make_manifest({"candidate_pool": str(tmp_path / "candidate_pool.jsonl")})
        op = make_output_paths(str(tmp_path))
        op.candidate_pool_path = str(tmp_path / "candidate_pool.jsonl")

        self._run(manifest, op, tmp_path)

        # The guard must not introduce a tool_events key
        assert "tool_events" not in manifest.artifact_paths

    def test_multiple_platform_keys_not_present_after_stripping(self, tmp_path):
        """
        Guard is defined as a set; if a second platform key is ever added to
        _PLATFORM_ONLY_KEYS it should also be stripped (forward-compat check
        using the existing set).
        """
        manifest = make_manifest(
            {
                "candidate_pool": str(tmp_path / "candidate_pool.jsonl"),
                "tool_events": "/agent/tool_events.jsonl",
            }
        )
        op = make_output_paths(str(tmp_path))
        op.candidate_pool_path = str(tmp_path / "candidate_pool.jsonl")
        self._run(manifest, op, tmp_path)

        assert "tool_events" not in manifest.artifact_paths


# ---------------------------------------------------------------------------
# _mark_needs_review — structured result_summary_json
# ---------------------------------------------------------------------------


class TestMarkNeedsReview:
    """
    Verifies that _mark_needs_review writes a structured result_summary_json
    via run_repo.complete().  All DB calls are mocked.
    """

    def _call(self, env, *, invocation_id, reason, error_code="SOME_ERROR",
              phase="unknown", result_summary_extra=None):
        from apps.worker.tasks.search_run import _mark_needs_review

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        mock_task_repo = MagicMock()
        mock_run_repo = MagicMock()
        mock_event_repo = MagicMock()

        with patch(
            "apps.worker.tasks.search_run.get_session", return_value=mock_session
        ), patch(
            "apps.worker.tasks.search_run.TaskRepository", return_value=mock_task_repo
        ), patch(
            "apps.worker.tasks.search_run.RunRepository", return_value=mock_run_repo
        ), patch(
            "apps.worker.tasks.search_run.TaskEventRepository", return_value=mock_event_repo
        ):
            _mark_needs_review(
                env,
                invocation_id=invocation_id,
                reason=reason,
                error_code=error_code,
                phase=phase,
                result_summary_extra=result_summary_extra,
            )

        return mock_run_repo, mock_task_repo, mock_event_repo

    def _get_summary(self, mock_run_repo) -> dict:
        """Extract result_summary passed to run_repo.complete()."""
        mock_run_repo.complete.assert_called_once()
        _, kwargs = mock_run_repo.complete.call_args
        return kwargs["result_summary"]

    # -- base fields always present -------------------------------------------

    def test_summary_contains_base_fields(self):
        env = make_envelope()
        mock_run_repo, _, _ = self._call(
            env,
            invocation_id="ainv_001",
            reason="something broke",
            error_code="FOO_ERROR",
            phase="validator_gate",
        )
        summary = self._get_summary(mock_run_repo)

        assert summary["validation_status"] == "failed"
        assert summary["phase"] == "validator_gate"
        assert summary["error_code"] == "FOO_ERROR"
        assert summary["invocation_id"] == "ainv_001"

    def test_invocation_id_none_is_preserved(self):
        """Early failures (before invocation is created) set invocation_id=None."""
        env = make_envelope()
        mock_run_repo, _, _ = self._call(
            env,
            invocation_id=None,
            reason="bad input",
            phase="input_validation",
        )
        summary = self._get_summary(mock_run_repo)
        assert summary["invocation_id"] is None

    def test_run_complete_called_with_needs_review_status(self):
        env = make_envelope()
        mock_run_repo, _, _ = self._call(
            env, invocation_id=None, reason="x", phase="input_validation"
        )
        _, kwargs = mock_run_repo.complete.call_args
        assert kwargs["status"] == "needs_review"

    # -- result_summary_extra merging -----------------------------------------

    def test_extra_fields_merged_into_summary(self):
        env = make_envelope()
        extra = {
            "failed_validators": [{"name": "ToolLedgerValidator", "errors": ["missing file"]}],
            "candidate_count": 3,
            "artifact_paths": {"output_manifest_path": "/tmp/manifest.json"},
        }
        mock_run_repo, _, _ = self._call(
            env,
            invocation_id="ainv_002",
            reason="ledger missing",
            phase="validator_gate",
            result_summary_extra=extra,
        )
        summary = self._get_summary(mock_run_repo)

        assert summary["failed_validators"] == extra["failed_validators"]
        assert summary["candidate_count"] == 3
        assert summary["artifact_paths"]["output_manifest_path"] == "/tmp/manifest.json"

    def test_no_extra_fields_when_none(self):
        """result_summary_extra=None does not add spurious keys."""
        env = make_envelope()
        mock_run_repo, _, _ = self._call(
            env,
            invocation_id=None,
            reason="x",
            phase="input_validation",
            result_summary_extra=None,
        )
        summary = self._get_summary(mock_run_repo)
        assert set(summary.keys()) == {
            "validation_status", "phase", "error_code", "invocation_id"
        }

    # -- task and event repos also called -------------------------------------

    def test_task_repo_mark_needs_review_called(self):
        env = make_envelope()
        _, mock_task_repo, _ = self._call(
            env, invocation_id=None, reason="x", error_code="ERR", phase="p"
        )
        mock_task_repo.mark_needs_review.assert_called_once_with(
            env.task_id,
            error_code="ERR",
            error_message="x",
        )

    def test_event_repo_append_called_with_reason(self):
        env = make_envelope()
        _, _, mock_event_repo = self._call(
            env, invocation_id=None, reason="something went wrong", phase="p"
        )
        mock_event_repo.append.assert_called_once()
        _, kwargs = mock_event_repo.append.call_args
        assert kwargs["event_type"] == "task_needs_review"
        assert kwargs["message"] == "something went wrong"

    def test_reason_truncated_to_500_chars_for_task_repo(self):
        """Long reasons are truncated at 500 chars when stored on the task."""
        env = make_envelope()
        long_reason = "x" * 600
        _, mock_task_repo, _ = self._call(
            env, invocation_id=None, reason=long_reason, error_code="E", phase="p"
        )
        _, kwargs = mock_task_repo.mark_needs_review.call_args
        assert len(kwargs["error_message"]) == 500

    def test_phase_unknown_default(self):
        """Default phase is 'unknown' when not supplied."""
        env = make_envelope()
        from apps.worker.tasks.search_run import _mark_needs_review

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_run_repo = MagicMock()

        with patch("apps.worker.tasks.search_run.get_session", return_value=mock_session), \
             patch("apps.worker.tasks.search_run.TaskRepository"), \
             patch("apps.worker.tasks.search_run.RunRepository", return_value=mock_run_repo), \
             patch("apps.worker.tasks.search_run.TaskEventRepository"):
            _mark_needs_review(env, invocation_id=None, reason="r")

        _, kwargs = mock_run_repo.complete.call_args
        assert kwargs["result_summary"]["phase"] == "unknown"

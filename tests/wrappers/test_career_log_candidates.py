"""
Unit tests for career_log_candidates — previously zero test coverage.

Covers core logging behavior plus the invocation_id correction fix (see
_manifest_identity.py): real-data testing on 2026-07-11 found the ledger's
signed candidate_log events getting the wrong invocation_id in 4/5 real runs,
which load_and_verify() then silently filters out as "belongs to a different
invocation" — producing a stale last-event hash that no longer matches the
real candidate_pool.jsonl content (DiscoveryEvidenceValidator failure).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

_WRAPPER_DIR = Path(__file__).resolve().parents[2] / "tools" / "wrappers" / "agent_tools"
sys.path.insert(0, str(_WRAPPER_DIR))

from career_log_candidates import main  # noqa: E402

_KEY = "test-signing-key-at-least-32-bytes-long!!"
_RUN_ID = "1906095d-6397-4c24-afaa-6b3ddd1f121f"
_TASK_ID = "ee8c6105-c47e-4847-b503-c7c2b6fb56c5"
_REAL_INVOCATION_ID = "d1b5c5d0-3ee4-4caa-81c3-e4ba8ef05271"

_CANDIDATE = {
    "url": "https://boards.greenhouse.io/acme/jobs/1",
    "title": "Market Risk Analyst",
    "company": "Acme Bank",
    "source_type": "greenhouse",
}


def _write_spec(path: Path, **overrides) -> Path:
    spec = {
        "run_id": _RUN_ID,
        "task_id": _TASK_ID,
        "candidates": [_CANDIDATE],
        **overrides,
    }
    path.write_text(json.dumps(spec))
    return path


class TestCareerLogCandidatesCore:
    def test_logs_valid_candidate(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        artifacts_root = tmp_path / "artifacts"
        monkeypatch.setenv("AGENT_ARTIFACTS_DIR", str(artifacts_root))
        spec_path = _write_spec(tmp_path / "spec.json", artifacts_dir=str(artifacts_root))
        output_path = tmp_path / "result.json"

        runner = CliRunner()
        result = runner.invoke(main, ["--task-spec", str(spec_path), "--output", str(output_path)])

        assert result.exit_code == 0, result.output
        pool_path = artifacts_root / _RUN_ID / _TASK_ID / "candidate_pool.jsonl"
        assert pool_path.exists()
        lines = [json.loads(l) for l in pool_path.read_text().splitlines() if l.strip()]
        assert len(lines) == 1
        assert lines[0]["url"] == _CANDIDATE["url"]

        output = json.loads(output_path.read_text())
        assert output["logged_count"] == 1
        assert output["errors"] == []

    def test_rejects_candidate_missing_required_fields(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        artifacts_root = tmp_path / "artifacts"
        monkeypatch.setenv("AGENT_ARTIFACTS_DIR", str(artifacts_root))
        bad_candidate = {"url": "https://example.com/job/1"}  # missing title/company/source_type
        spec_path = _write_spec(tmp_path / "spec.json", artifacts_dir=str(artifacts_root), candidates=[bad_candidate])
        output_path = tmp_path / "result.json"

        runner = CliRunner()
        result = runner.invoke(main, ["--task-spec", str(spec_path), "--output", str(output_path)])

        assert result.exit_code == 0, result.output
        output = json.loads(output_path.read_text())
        assert output["logged_count"] == 0
        assert len(output["errors"]) == 1

    def test_rejects_invalid_url_scheme(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        artifacts_root = tmp_path / "artifacts"
        monkeypatch.setenv("AGENT_ARTIFACTS_DIR", str(artifacts_root))
        bad_candidate = {**_CANDIDATE, "url": "ftp://example.com/job/1"}
        spec_path = _write_spec(tmp_path / "spec.json", artifacts_dir=str(artifacts_root), candidates=[bad_candidate])
        output_path = tmp_path / "result.json"

        runner = CliRunner()
        result = runner.invoke(main, ["--task-spec", str(spec_path), "--output", str(output_path)])

        assert result.exit_code == 0, result.output
        output = json.loads(output_path.read_text())
        assert output["logged_count"] == 0
        assert "http" in output["errors"][0]["error"]


class TestCareerLogCandidatesInvocationIdCorrection:
    def test_wrong_invocation_id_gets_corrected_in_signed_ledger(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        artifacts_root = tmp_path / "artifacts"
        monkeypatch.setenv("AGENT_ARTIFACTS_DIR", str(artifacts_root))
        monkeypatch.setenv("TOOL_LEDGER_SIGNING_KEY", _KEY)

        run_dir = artifacts_root / _RUN_ID / _TASK_ID
        run_dir.mkdir(parents=True)
        (run_dir / "input.json").write_text(
            json.dumps({"invocation_id": _REAL_INVOCATION_ID, "run_id": _RUN_ID, "task_id": _TASK_ID})
        )
        tool_events_path = run_dir / "tool_events.jsonl"

        spec_path = _write_spec(
            tmp_path / "spec.json",
            artifacts_dir=str(artifacts_root),
            invocation_id=_RUN_ID,  # the exact real-world mistake: run_id's value
            output_paths={"tool_events_path": str(tool_events_path)},
        )
        output_path = tmp_path / "result.json"

        runner = CliRunner()
        result = runner.invoke(main, ["--task-spec", str(spec_path), "--output", str(output_path)])

        assert result.exit_code == 0, result.output
        ledger_lines = [json.loads(l) for l in tool_events_path.read_text().splitlines() if l.strip()]
        candidate_log_events = [e for e in ledger_lines if e["event_type"] == "candidate_log"]
        assert len(candidate_log_events) == 1
        assert candidate_log_events[0]["invocation_id"] == _REAL_INVOCATION_ID, (
            "must be corrected — a wrong invocation_id here gets silently filtered out by "
            "load_and_verify(), producing a stale last-event hash at validation time"
        )

    def test_multiple_calls_each_get_correct_invocation_id(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """
        Reproduces the exact real-world sequence: first call correct, later calls
        drift to run_id's value. All signed events must end up consistent regardless.
        """
        artifacts_root = tmp_path / "artifacts"
        monkeypatch.setenv("AGENT_ARTIFACTS_DIR", str(artifacts_root))
        monkeypatch.setenv("TOOL_LEDGER_SIGNING_KEY", _KEY)

        run_dir = artifacts_root / _RUN_ID / _TASK_ID
        run_dir.mkdir(parents=True)
        (run_dir / "input.json").write_text(
            json.dumps({"invocation_id": _REAL_INVOCATION_ID, "run_id": _RUN_ID, "task_id": _TASK_ID})
        )
        tool_events_path = run_dir / "tool_events.jsonl"

        runner = CliRunner()
        for call_index, reported_invocation_id in enumerate([_REAL_INVOCATION_ID, _RUN_ID, _RUN_ID]):
            candidate = {**_CANDIDATE, "url": f"https://boards.greenhouse.io/acme/jobs/{call_index}"}
            spec_path = _write_spec(
                tmp_path / f"spec_{call_index}.json",
                artifacts_dir=str(artifacts_root),
                invocation_id=reported_invocation_id,
                candidates=[candidate],
                output_paths={"tool_events_path": str(tool_events_path)},
            )
            result = runner.invoke(
                main, ["--task-spec", str(spec_path), "--output", str(tmp_path / f"result_{call_index}.json")]
            )
            assert result.exit_code == 0, result.output

        pool_path = run_dir / "candidate_pool.jsonl"
        real_hash = "sha256:" + __import__("hashlib").sha256(pool_path.read_bytes()).hexdigest()

        ledger_lines = [json.loads(l) for l in tool_events_path.read_text().splitlines() if l.strip()]
        candidate_log_events = [e for e in ledger_lines if e["event_type"] == "candidate_log"]
        assert len(candidate_log_events) == 3
        assert all(e["invocation_id"] == _REAL_INVOCATION_ID for e in candidate_log_events), (
            "every event must carry the same real invocation_id so load_and_verify() keeps all of them"
        )
        assert candidate_log_events[-1]["output_hash"] == real_hash, (
            "last event's hash must match the true final file — this is exactly what "
            "DiscoveryEvidenceValidator checks"
        )

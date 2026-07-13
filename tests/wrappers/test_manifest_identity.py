"""
Unit tests for resolve_invocation_id — the shared fix for the invocation_id/run_id
mix-up found in real-data testing (2026-07-11 5-round discovery/reflect loop test,
4/5 real runs had the agent write run_id's value into the invocation_id field).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_WRAPPER_DIR = Path(__file__).resolve().parents[2] / "tools" / "wrappers" / "agent_tools"
sys.path.insert(0, str(_WRAPPER_DIR))

from _manifest_identity import resolve_invocation_id, resolve_run_task_ids  # noqa: E402

_RUN_ID = "1906095d-6397-4c24-afaa-6b3ddd1f121f"
_TASK_ID = "ee8c6105-c47e-4847-b503-c7c2b6fb56c5"
_REAL_INVOCATION_ID = "d1b5c5d0-3ee4-4caa-81c3-e4ba8ef05271"
_REFLECTED_RUN_ID = "faa66b08-9d36-4ac0-bf57-90142e55350e"  # a *different* run's id


def _write_input_json(artifacts_dir: Path, invocation_id: str) -> None:
    run_dir = artifacts_dir / _RUN_ID / _TASK_ID
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "input.json").write_text(json.dumps({"invocation_id": invocation_id, "run_id": _RUN_ID, "task_id": _TASK_ID}))


class TestResolveInvocationId:
    def test_corrects_agent_reported_run_id_mixup(self, tmp_path: Path):
        """The exact real-world failure: agent wrote run_id's value into invocation_id."""
        _write_input_json(tmp_path, _REAL_INVOCATION_ID)
        spec = {"invocation_id": _RUN_ID, "run_id": _RUN_ID, "task_id": _TASK_ID}  # agent's mistake

        assert resolve_invocation_id(spec, tmp_path) == _REAL_INVOCATION_ID

    def test_passes_through_when_agent_already_correct(self, tmp_path: Path):
        _write_input_json(tmp_path, _REAL_INVOCATION_ID)
        spec = {"invocation_id": _REAL_INVOCATION_ID, "run_id": _RUN_ID, "task_id": _TASK_ID}

        assert resolve_invocation_id(spec, tmp_path) == _REAL_INVOCATION_ID

    def test_falls_back_to_agent_value_when_input_json_missing(self, tmp_path: Path):
        """No input.json on disk — never a new hard-failure mode, just degrade to old behavior."""
        spec = {"invocation_id": "whatever-agent-said", "run_id": _RUN_ID, "task_id": _TASK_ID}

        assert resolve_invocation_id(spec, tmp_path) == "whatever-agent-said"

    def test_falls_back_when_input_json_malformed(self, tmp_path: Path):
        run_dir = tmp_path / _RUN_ID / _TASK_ID
        run_dir.mkdir(parents=True)
        (run_dir / "input.json").write_text("{not valid json")
        spec = {"invocation_id": "agent-value", "run_id": _RUN_ID, "task_id": _TASK_ID}

        assert resolve_invocation_id(spec, tmp_path) == "agent-value"

    def test_falls_back_when_run_id_or_task_id_missing(self, tmp_path: Path):
        _write_input_json(tmp_path, _REAL_INVOCATION_ID)
        spec = {"invocation_id": "agent-value", "run_id": "", "task_id": _TASK_ID}

        assert resolve_invocation_id(spec, tmp_path) == "agent-value"

    def test_falls_back_when_input_json_invocation_id_empty(self, tmp_path: Path):
        _write_input_json(tmp_path, "")
        spec = {"invocation_id": "agent-value", "run_id": _RUN_ID, "task_id": _TASK_ID}

        assert resolve_invocation_id(spec, tmp_path) == "agent-value"


class TestResolveRunTaskIds:
    """
    Covers the run_reflection failure mode found in real HTTP-path testing
    (2026-07-12): the reflect agent has two run identities in context — its own
    run and payload.reflected_run_id (the discovery run it's analyzing) — and
    sometimes writes the latter into run_id/task_id/output_manifest_path. See
    dev_note/career/phase20-launch-hardening/openclaw_http_migration_0712.
    """

    def test_corrects_agent_reported_reflected_run_id_mixup(self, monkeypatch):
        """The exact real-world failure: agent wrote reflected_run_id's value into run_id."""
        monkeypatch.setenv("CAREER_TRUE_RUN_ID", _RUN_ID)
        monkeypatch.setenv("CAREER_TRUE_TASK_ID", _TASK_ID)
        spec = {"run_id": _REFLECTED_RUN_ID, "task_id": _TASK_ID}  # agent's mistake

        run_id, task_id, trusted = resolve_run_task_ids(spec)

        assert (run_id, task_id, trusted) == (_RUN_ID, _TASK_ID, True)

    def test_passes_through_when_agent_already_correct(self, monkeypatch):
        monkeypatch.setenv("CAREER_TRUE_RUN_ID", _RUN_ID)
        monkeypatch.setenv("CAREER_TRUE_TASK_ID", _TASK_ID)
        spec = {"run_id": _RUN_ID, "task_id": _TASK_ID}

        assert resolve_run_task_ids(spec) == (_RUN_ID, _TASK_ID, True)

    def test_falls_back_untrusted_when_env_vars_absent(self, monkeypatch):
        """Plugin not installed in this environment — degrade to agent-reported values."""
        monkeypatch.delenv("CAREER_TRUE_RUN_ID", raising=False)
        monkeypatch.delenv("CAREER_TRUE_TASK_ID", raising=False)
        spec = {"run_id": _REFLECTED_RUN_ID, "task_id": _TASK_ID}

        assert resolve_run_task_ids(spec) == (_REFLECTED_RUN_ID, _TASK_ID, False)

    def test_falls_back_untrusted_when_only_one_env_var_set(self, monkeypatch):
        monkeypatch.setenv("CAREER_TRUE_RUN_ID", _RUN_ID)
        monkeypatch.delenv("CAREER_TRUE_TASK_ID", raising=False)
        spec = {"run_id": _REFLECTED_RUN_ID, "task_id": _TASK_ID}

        assert resolve_run_task_ids(spec) == (_REFLECTED_RUN_ID, _TASK_ID, False)

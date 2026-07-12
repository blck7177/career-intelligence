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

from _manifest_identity import resolve_invocation_id  # noqa: E402

_RUN_ID = "1906095d-6397-4c24-afaa-6b3ddd1f121f"
_TASK_ID = "ee8c6105-c47e-4847-b503-c7c2b6fb56c5"
_REAL_INVOCATION_ID = "d1b5c5d0-3ee4-4caa-81c3-e4ba8ef05271"


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

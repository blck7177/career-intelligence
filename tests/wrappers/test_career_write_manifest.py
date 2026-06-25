"""
Regression tests for career_write_manifest canonical path resolution.

Prevents LLM UUID typos in --output from writing manifests outside the run directory.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

# Wrapper lives outside packages/; import by path.
_WRAPPER_DIR = Path(__file__).resolve().parents[2] / "tools" / "wrappers" / "agent_tools"
sys.path.insert(0, str(_WRAPPER_DIR))

from career_write_manifest import main, resolve_manifest_output_path  # noqa: E402

_KEY = "test-signing-key-at-least-32-bytes-long!!"
_CORRECT_RUN_ID = "f424ff50-8260-4224-9eeb-dcd8a637e006"
_WRONG_RUN_ID = "f424ff50-8260-4224-9eb-dcd8a637e006"
_TASK_ID = "ab230dfb-3eb8-45a0-89d8-9ba55d14da90"


def _base_spec(artifacts_root: Path) -> dict:
    canonical = artifacts_root / _CORRECT_RUN_ID / _TASK_ID / "output_manifest.json"
    tool_events = artifacts_root / _CORRECT_RUN_ID / _TASK_ID / "tool_events.jsonl"
    return {
        "invocation_id": "07843787-69f7-44ac-b294-adcfcee989ab",
        "run_id": _CORRECT_RUN_ID,
        "task_id": _TASK_ID,
        "status": "completed",
        "stop_reason": "test",
        "candidate_count": 2,
        "sources_tried": ["example.com"],
        "sources_added": [],
        "output_paths": {
            "output_manifest_path": str(canonical),
            "tool_events_path": str(tool_events),
        },
        "artifact_paths": {},
        "summary": {"candidate_count": 2},
    }


class TestResolveManifestOutputPath:
    def test_prefers_output_paths_output_manifest_path(self, tmp_path: Path):
        spec = {
            "run_id": _CORRECT_RUN_ID,
            "task_id": _TASK_ID,
            "output_paths": {"output_manifest_path": str(tmp_path / "custom" / "manifest.json")},
        }
        assert resolve_manifest_output_path(spec) == tmp_path / "custom" / "manifest.json"

    def test_fallback_artifacts_dir_run_task(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("AGENT_ARTIFACTS_DIR", str(tmp_path))
        spec = {"run_id": _CORRECT_RUN_ID, "task_id": _TASK_ID}
        assert resolve_manifest_output_path(spec) == (
            tmp_path / _CORRECT_RUN_ID / _TASK_ID / "output_manifest.json"
        )

    def test_missing_run_id_raises(self):
        with pytest.raises(ValueError, match="output_manifest_path"):
            resolve_manifest_output_path({"task_id": _TASK_ID})


class TestCareerWriteManifestCanonicalWrite:
    def test_wrong_cli_output_still_writes_canonical_manifest(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        artifacts_root = tmp_path / "artifacts"
        artifacts_root.mkdir()
        monkeypatch.setenv("AGENT_ARTIFACTS_DIR", str(artifacts_root))
        monkeypatch.setenv("TOOL_LEDGER_SIGNING_KEY", _KEY)

        spec = _base_spec(artifacts_root)
        canonical = Path(spec["output_paths"]["output_manifest_path"])
        wrong_manifest = artifacts_root / _WRONG_RUN_ID / _TASK_ID / "output_manifest.json"
        wrong_manifest.parent.mkdir(parents=True, exist_ok=True)

        spec_path = tmp_path / "manifest_spec.json"
        spec_path.write_text(json.dumps(spec))
        ack_path = tmp_path / "ack.json"

        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                main,
                [
                    "--task-spec",
                    str(spec_path),
                    "--output",
                    str(wrong_manifest),
                ],
            )

        assert result.exit_code == 0, result.output
        assert canonical.exists(), "canonical manifest must exist"
        if wrong_manifest.exists():
            wrong_payload = json.loads(wrong_manifest.read_text())
            assert "artifact_paths" not in wrong_payload, "wrong --output must not receive platform manifest"
        else:
            pass  # ack may land elsewhere when --output is not the wrong manifest path

        manifest = json.loads(canonical.read_text())
        assert manifest["status"] == "completed"
        assert manifest["candidate_count"] == 2

        tool_events_path = Path(spec["output_paths"]["tool_events_path"])
        assert tool_events_path.exists()
        ledger_lines = [json.loads(line) for line in tool_events_path.read_text().splitlines() if line.strip()]
        manifest_events = [e for e in ledger_lines if e.get("event_type") == "manifest_write"]
        assert len(manifest_events) == 1
        assert manifest_events[0]["output_path"] == str(canonical)

    def test_fallback_path_when_output_manifest_path_omitted(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        artifacts_root = tmp_path / "artifacts"
        artifacts_root.mkdir()
        monkeypatch.setenv("AGENT_ARTIFACTS_DIR", str(artifacts_root))
        monkeypatch.setenv("TOOL_LEDGER_SIGNING_KEY", _KEY)

        tool_events = artifacts_root / _CORRECT_RUN_ID / _TASK_ID / "tool_events.jsonl"
        spec = {
            "invocation_id": "inv-1",
            "run_id": _CORRECT_RUN_ID,
            "task_id": _TASK_ID,
            "status": "completed",
            "stop_reason": "test",
            "output_paths": {"tool_events_path": str(tool_events)},
            "artifact_paths": {},
            "summary": {},
        }
        canonical = artifacts_root / _CORRECT_RUN_ID / _TASK_ID / "output_manifest.json"

        spec_path = tmp_path / "manifest_spec.json"
        spec_path.write_text(json.dumps(spec))

        runner = CliRunner()
        result = runner.invoke(main, ["--task-spec", str(spec_path), "--output", str(tmp_path / "ack.json")])

        assert result.exit_code == 0, result.output
        assert canonical.exists()

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
        assert resolve_manifest_output_path(spec, _CORRECT_RUN_ID, _TASK_ID, False, tmp_path) == (
            tmp_path / "custom" / "manifest.json"
        )

    def test_fallback_artifacts_dir_run_task(self, tmp_path: Path):
        spec = {"run_id": _CORRECT_RUN_ID, "task_id": _TASK_ID}
        assert resolve_manifest_output_path(spec, _CORRECT_RUN_ID, _TASK_ID, False, tmp_path) == (
            tmp_path / _CORRECT_RUN_ID / _TASK_ID / "output_manifest.json"
        )

    def test_missing_run_id_raises(self, tmp_path: Path):
        with pytest.raises(ValueError, match="output_manifest_path"):
            resolve_manifest_output_path({"task_id": _TASK_ID}, "", _TASK_ID, False, tmp_path)

    def test_trusted_ids_ignore_output_paths(self, tmp_path: Path):
        """When run_id/task_id are trusted (env-injected), output_paths.output_manifest_path
        must be ignored even if the agent supplied one — that field is exactly what a
        confused agent can point at a different run's directory."""
        spec = {
            "run_id": "agent-typo-run-id",
            "task_id": _TASK_ID,
            "output_paths": {"output_manifest_path": str(tmp_path / "some-other-runs-dir" / "manifest.json")},
        }
        assert resolve_manifest_output_path(spec, _CORRECT_RUN_ID, _TASK_ID, True, tmp_path) == (
            tmp_path / _CORRECT_RUN_ID / _TASK_ID / "output_manifest.json"
        )


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

    def test_same_path_as_output_does_not_clobber_manifest(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Agent may still pass canonical path as --output; manifest must survive."""
        artifacts_root = tmp_path / "artifacts"
        artifacts_root.mkdir()
        monkeypatch.setenv("AGENT_ARTIFACTS_DIR", str(artifacts_root))
        monkeypatch.setenv("TOOL_LEDGER_SIGNING_KEY", _KEY)

        spec = _base_spec(artifacts_root)
        canonical = Path(spec["output_paths"]["output_manifest_path"])
        canonical.parent.mkdir(parents=True, exist_ok=True)

        spec_path = tmp_path / "manifest_spec.json"
        spec_path.write_text(json.dumps(spec))

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--task-spec", str(spec_path), "--output", str(canonical)],
        )

        assert result.exit_code == 0, result.output
        payload = json.loads(canonical.read_text())
        assert payload["status"] == "completed"
        assert payload["invocation_id"] == spec["invocation_id"]
        assert payload["candidate_count"] == 2
        assert "manifest_path" not in payload, "ack must not overwrite platform manifest"


class TestInvocationIdCorrection:
    """
    Regression coverage for the real failure found in 2026-07-11 5-round testing:
    the agent wrote run_id's value into invocation_id in 4/5 real discovery runs,
    which SchemaValidator correctly rejects and which silently corrupts
    DiscoveryEvidenceValidator's ledger-hash check (see _manifest_identity.py).
    """

    def test_wrong_invocation_id_gets_corrected_from_input_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        artifacts_root = tmp_path / "artifacts"
        artifacts_root.mkdir()
        monkeypatch.setenv("AGENT_ARTIFACTS_DIR", str(artifacts_root))
        monkeypatch.setenv("TOOL_LEDGER_SIGNING_KEY", _KEY)

        real_invocation_id = "d1b5c5d0-3ee4-4caa-81c3-e4ba8ef05271"
        run_dir = artifacts_root / _CORRECT_RUN_ID / _TASK_ID
        run_dir.mkdir(parents=True)
        (run_dir / "input.json").write_text(
            json.dumps({"invocation_id": real_invocation_id, "run_id": _CORRECT_RUN_ID, "task_id": _TASK_ID})
        )

        spec = _base_spec(artifacts_root)
        spec["invocation_id"] = _CORRECT_RUN_ID  # the exact real-world mistake: run_id's value
        canonical = Path(spec["output_paths"]["output_manifest_path"])

        spec_path = tmp_path / "manifest_spec.json"
        spec_path.write_text(json.dumps(spec))

        runner = CliRunner()
        result = runner.invoke(main, ["--task-spec", str(spec_path), "--output", str(tmp_path / "ack.json")])

        assert result.exit_code == 0, result.output
        manifest = json.loads(canonical.read_text())
        assert manifest["invocation_id"] == real_invocation_id, "must be corrected, not the agent's run_id typo"

        tool_events_path = Path(spec["output_paths"]["tool_events_path"])
        ledger_lines = [json.loads(line) for line in tool_events_path.read_text().splitlines() if line.strip()]
        manifest_events = [e for e in ledger_lines if e.get("event_type") == "manifest_write"]
        assert manifest_events[0]["invocation_id"] == real_invocation_id, "ledger event must also carry the corrected id"

    def test_no_input_json_falls_back_to_agent_reported_value(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """No behavior change when input.json isn't there — purely additive robustness."""
        artifacts_root = tmp_path / "artifacts"
        artifacts_root.mkdir()
        monkeypatch.setenv("AGENT_ARTIFACTS_DIR", str(artifacts_root))
        monkeypatch.setenv("TOOL_LEDGER_SIGNING_KEY", _KEY)

        spec = _base_spec(artifacts_root)
        canonical = Path(spec["output_paths"]["output_manifest_path"])

        spec_path = tmp_path / "manifest_spec.json"
        spec_path.write_text(json.dumps(spec))

        runner = CliRunner()
        result = runner.invoke(main, ["--task-spec", str(spec_path), "--output", str(tmp_path / "ack.json")])

        assert result.exit_code == 0, result.output
        manifest = json.loads(canonical.read_text())
        assert manifest["invocation_id"] == spec["invocation_id"]


class TestRunTaskIdCorrection:
    """
    Regression coverage for the real failure found in 2026-07-12 HTTP-path testing:
    the reflect agent wrote the discovery run's id (payload.reflected_run_id) into
    run_id/output_paths.output_manifest_path, and wrote reflection_report.md/
    strategy_patch.json straight into the discovery run's own directory — landing
    real files in a different run's task directory (see
    dev_note/career/phase20-launch-hardening/openclaw_http_migration_0712 and
    _manifest_identity.py::resolve_run_task_ids).
    """

    def test_wrong_run_id_and_foreign_artifact_get_corrected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        artifacts_root = tmp_path / "artifacts"
        artifacts_root.mkdir()
        monkeypatch.setenv("AGENT_ARTIFACTS_DIR", str(artifacts_root))
        monkeypatch.setenv("TOOL_LEDGER_SIGNING_KEY", _KEY)
        monkeypatch.setenv("CAREER_TRUE_RUN_ID", _CORRECT_RUN_ID)
        monkeypatch.setenv("CAREER_TRUE_TASK_ID", _TASK_ID)

        reflected_run_id = "faa66b08-9d36-4ac0-bf57-90142e55350e"  # a *different* run
        reflected_task_id = "0f4f1927-0000-4000-8000-000000000000"

        # A real file sitting in the OTHER run's directory — simulates the agent
        # having written reflection_report.md there by mistake.
        foreign_dir = artifacts_root / reflected_run_id / reflected_task_id
        foreign_dir.mkdir(parents=True)
        foreign_report = foreign_dir / "reflection_report.md"
        foreign_report.write_text("misplaced report")

        canonical = artifacts_root / _CORRECT_RUN_ID / _TASK_ID / "output_manifest.json"
        tool_events = artifacts_root / _CORRECT_RUN_ID / _TASK_ID / "tool_events.jsonl"

        spec = {
            "invocation_id": "07843787-69f7-44ac-b294-adcfcee989ab",
            # the exact real-world mistake: run_id/output path point at the
            # reflected (discovery) run instead of this reflection's own run
            "run_id": reflected_run_id,
            "task_id": _TASK_ID,
            "status": "completed",
            "stop_reason": "test",
            "artifact_paths": {"reflection_report": str(foreign_report)},
            "summary": {},
            "output_paths": {
                "output_manifest_path": str(
                    artifacts_root / reflected_run_id / _TASK_ID / "output_manifest.json"
                ),
                "tool_events_path": str(tool_events),
            },
        }
        spec_path = tmp_path / "manifest_spec.json"
        spec_path.write_text(json.dumps(spec))

        runner = CliRunner()
        result = runner.invoke(main, ["--task-spec", str(spec_path), "--output", str(tmp_path / "ack.json")])

        assert result.exit_code == 0, result.output
        assert canonical.exists(), "manifest must land under the trusted run/task directory"

        manifest = json.loads(canonical.read_text())
        assert manifest["run_id"] == _CORRECT_RUN_ID, "run_id must be the trusted one, not reflected_run_id"
        assert manifest["artifact_paths"] == {}, "artifact pointing into the other run's dir must be dropped"

        ledger_lines = [json.loads(line) for line in tool_events.read_text().splitlines() if line.strip()]
        manifest_events = [e for e in ledger_lines if e.get("event_type") == "manifest_write"]
        assert manifest_events[0]["run_id"] == _CORRECT_RUN_ID
        assert manifest_events[0]["task_id"] == _TASK_ID

    def test_own_artifact_paths_survive_when_trusted(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Trusted-ids correction must not collateral-damage artifacts that are
        genuinely inside this run's own directory."""
        artifacts_root = tmp_path / "artifacts"
        artifacts_root.mkdir()
        monkeypatch.setenv("AGENT_ARTIFACTS_DIR", str(artifacts_root))
        monkeypatch.setenv("TOOL_LEDGER_SIGNING_KEY", _KEY)
        monkeypatch.setenv("CAREER_TRUE_RUN_ID", _CORRECT_RUN_ID)
        monkeypatch.setenv("CAREER_TRUE_TASK_ID", _TASK_ID)

        own_dir = artifacts_root / _CORRECT_RUN_ID / _TASK_ID
        own_dir.mkdir(parents=True)
        own_report = own_dir / "reflection_report.md"
        own_report.write_text("real report")

        tool_events = own_dir / "tool_events.jsonl"
        spec = {
            "invocation_id": "07843787-69f7-44ac-b294-adcfcee989ab",
            "run_id": _CORRECT_RUN_ID,
            "task_id": _TASK_ID,
            "status": "completed",
            "stop_reason": "test",
            "artifact_paths": {"reflection_report": str(own_report)},
            "summary": {},
            "output_paths": {"tool_events_path": str(tool_events)},
        }
        spec_path = tmp_path / "manifest_spec.json"
        spec_path.write_text(json.dumps(spec))

        runner = CliRunner()
        result = runner.invoke(main, ["--task-spec", str(spec_path), "--output", str(tmp_path / "ack.json")])

        assert result.exit_code == 0, result.output
        manifest = json.loads((own_dir / "output_manifest.json").read_text())
        assert manifest["artifact_paths"] == {"reflection_report": str(own_report)}

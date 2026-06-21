from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from packages.contracts.agents.invocation import AgentInvocationSpec
from packages.infrastructure.agent_runtime.openclaw import OpenClawGatewayRuntime


def _make_spec(tmp_path: Path) -> AgentInvocationSpec:
    return AgentInvocationSpec(
        invocation_id="ainv_runtime_test",
        run_id="run_001",
        task_id="task_001",
        workspace_id="ws_001",
        agent_id="career-search-agent",
        skill_contract_version="career-search-v1",
        session_key="agent:career-search-agent:workspace:ws_001:run:run_001:task:task_001:attempt:1",
        input_spec_path=str(tmp_path / "input.json"),
        output_manifest_path=str(tmp_path / "output_manifest.json"),
        created_at=datetime.now(timezone.utc),
    )


def test_invoke_rejects_embedded_transport(monkeypatch, tmp_path):
    payload = {"result": {"meta": {"transport": "embedded"}}}

    def fake_run(cmd, capture_output, text, timeout, env):
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout=json.dumps(payload),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    runtime = OpenClawGatewayRuntime(openclaw_bin="openclaw")
    result = runtime.invoke(_make_spec(tmp_path))

    assert result.exit_code == 1
    assert "Gateway transport validation failed" in result.stderr
    assert result.tool_activity_summary_path is not None

    summary = json.loads(Path(result.tool_activity_summary_path).read_text())
    assert summary["transport"] == "embedded"


def test_invoke_extracts_tool_calls_from_session_file(monkeypatch, tmp_path):
    session_file = tmp_path / "session.jsonl"
    session_file.write_text(
        json.dumps(
            {
                "content": [
                    {
                        "type": "toolCall",
                        "name": "web_search",
                        "status": "succeeded",
                        "timestamp": "2026-06-21T00:00:00Z",
                    },
                    {
                        "type": "toolCall",
                        "name": "exec",
                        "arguments": {
                            "command": (
                                "python3 /app/tools/wrappers/agent_tools/"
                                "career_fetch_source.py --task-spec /tmp/x --output /tmp/y"
                            )
                        },
                        "status": "succeeded",
                    },
                ]
            }
        )
        + "\n"
    )

    payload = {
        "result": {
            "meta": {
                "transport": "gateway",
                "agentMeta": {"sessionFile": str(session_file)},
            }
        }
    }

    def fake_run(cmd, capture_output, text, timeout, env):
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout=json.dumps(payload),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    runtime = OpenClawGatewayRuntime(openclaw_bin="openclaw")
    result = runtime.invoke(_make_spec(tmp_path))

    assert result.exit_code == 0
    assert result.tool_activity_summary_path is not None

    summary = json.loads(Path(result.tool_activity_summary_path).read_text())
    tool_names = {c["tool"] for c in summary["tool_calls"]}
    assert summary["tool_call_count"] == 2
    assert "web_search" in tool_names
    assert "career_fetch_source" in tool_names

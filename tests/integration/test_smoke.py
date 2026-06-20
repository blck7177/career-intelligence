"""
End-to-end smoke tests for the agent workflow: discovery → validate → persist.

These tests exercise the full path from task envelope → manifest → validator gate
without requiring a live database or OpenClaw installation.

They verify that:
  1. All three agent task types route to the correct handler
  2. A valid manifest passes the validator gate
  3. An invalid manifest (missing file, wrong invocation_id) is rejected
  4. The execute_task OPENCLAW dispatch table is complete and correct
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from packages.contracts.agents.invocation import AgentBudget, AgentInvocationSpec
from packages.contracts.agents.manifests import (
    DiscoveryManifest,
    ReflectionManifest,
    ResearchManifest,
)
from packages.contracts.agents.validation import AgentValidationResult
from packages.domain.agent_jobs.planner import build_invocation_spec, build_session_key
from packages.domain.agent_jobs.routing import ExecutionMode, route_task
from packages.infrastructure.agent_runtime.validator import ValidatorGate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_spec(
    task_type: str = "agent.job_discovery",
    invocation_id: str = "ainv_smoke",
    run_id: str = "run_smoke",
    task_id: str = "task_smoke",
) -> AgentInvocationSpec:
    return AgentInvocationSpec(
        invocation_id=invocation_id,
        run_id=run_id,
        task_id=task_id,
        workspace_id="ws_smoke",
        agent_id="career-search-agent",
        skill_contract_version="career-search-v1",
        session_key=build_session_key(
            "career-search-agent", "ws_smoke", run_id, task_id, 1
        ),
        input_spec_path="/tmp/smoke_input.json",
        output_manifest_path="/tmp/smoke_output_manifest.json",
        created_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# 1. Routing smoke tests
# ---------------------------------------------------------------------------


class TestTaskRouting:
    def test_discovery_routes_to_openclaw(self):
        assert route_task("agent.job_discovery") == ExecutionMode.OPENCLAW

    def test_research_routes_to_openclaw(self):
        assert route_task("agent.job_research") == ExecutionMode.OPENCLAW

    def test_reflection_routes_to_openclaw(self):
        assert route_task("agent.run_reflection") == ExecutionMode.OPENCLAW

    def test_job_report_routes_deterministic(self):
        assert route_task("job_report") == ExecutionMode.DETERMINISTIC

    def test_fit_report_routes_deterministic(self):
        assert route_task("fit_report") == ExecutionMode.DETERMINISTIC

    def test_execute_task_openclaw_dispatch_table_covers_all_types(self):
        """
        Ensures _OPENCLAW_HANDLERS in execute_task covers every task_type
        that route_task() classifies as OPENCLAW.
        """
        from apps.worker.tasks.execute_task import _OPENCLAW_HANDLERS
        from packages.domain.agent_jobs.routing import _OPENCLAW_TASK_TYPES

        for task_type in _OPENCLAW_TASK_TYPES:
            assert task_type in _OPENCLAW_HANDLERS, (
                f"task_type={task_type!r} is classified as OPENCLAW but has no "
                "handler in execute_task._OPENCLAW_HANDLERS"
            )


# ---------------------------------------------------------------------------
# 2. Session key smoke test
# ---------------------------------------------------------------------------


class TestSessionKey:
    def test_session_key_format(self):
        key = build_session_key(
            agent_id="career-search-agent",
            workspace_id="ws_001",
            run_id="run_abc",
            task_id="task_xyz",
            attempt=1,
        )
        assert "agent:career-search-agent" in key
        assert "workspace:ws_001" in key
        assert "run:run_abc" in key
        assert "task:task_xyz" in key
        assert "attempt:1" in key

    def test_different_attempts_produce_different_keys(self):
        k1 = build_session_key("a", "w", "r", "t", 1)
        k2 = build_session_key("a", "w", "r", "t", 2)
        assert k1 != k2


# ---------------------------------------------------------------------------
# 3. Discovery manifest smoke test (full gate pass)
# ---------------------------------------------------------------------------


class TestDiscoveryManifestSmoke:
    def test_valid_manifest_passes_gate(self, tmp_path):
        pool_path = tmp_path / "candidate_pool.jsonl"
        pool_path.write_text(
            json.dumps(
                {"url": "https://example.com/job/1", "title": "Quant Dev", "source_type": "ats"}
            )
            + "\n"
        )
        ledger_path = tmp_path / "search_ledger.jsonl"
        ledger_path.write_text("{}\n")

        spec = make_spec("agent.job_discovery", invocation_id="ainv_smoke")
        manifest = DiscoveryManifest(
            invocation_id="ainv_smoke",
            status="completed",
            stop_reason="max_candidates_reached",
            artifact_paths={
                "candidate_pool": str(pool_path),
                "search_ledger": str(ledger_path),
            },
            candidate_count=1,
            sources_tried=["greenhouse.io"],
        )

        gate = ValidatorGate()
        results = gate.run(manifest, spec)
        assert gate.all_passed(results), [r.model_dump() for r in results if not r.passed]

    def test_manifest_with_missing_artifact_fails_gate(self):
        spec = make_spec("agent.job_discovery", invocation_id="ainv_smoke")
        manifest = DiscoveryManifest(
            invocation_id="ainv_smoke",
            status="completed",
            stop_reason="done",
            artifact_paths={"candidate_pool": "/nonexistent/path/pool.jsonl"},
            candidate_count=5,
        )

        gate = ValidatorGate()
        results = gate.run(manifest, spec)
        assert not gate.all_passed(results)
        failed = [r for r in results if r.status == "failed"]
        assert any(r.validator_name == "provenance" for r in failed)

    def test_manifest_with_wrong_invocation_id_fails_gate(self):
        spec = make_spec("agent.job_discovery", invocation_id="ainv_real")
        manifest = DiscoveryManifest(
            invocation_id="ainv_wrong",
            status="completed",
            stop_reason="done",
            candidate_count=0,
        )

        gate = ValidatorGate()
        results = gate.run(manifest, spec)
        assert not gate.all_passed(results)
        failed = [r for r in results if r.status == "failed"]
        assert any(r.validator_name == "schema" for r in failed)

    def test_agent_failed_status_rejects_manifest(self):
        spec = make_spec(invocation_id="ainv_smoke")
        manifest = DiscoveryManifest(
            invocation_id="ainv_smoke",
            status="failed",
            stop_reason="agent_error",
            candidate_count=0,
        )

        gate = ValidatorGate()
        results = gate.run(manifest, spec)
        assert not gate.all_passed(results)


# ---------------------------------------------------------------------------
# 4. Research manifest smoke test
# ---------------------------------------------------------------------------


class TestResearchManifestSmoke:
    def test_valid_research_manifest_passes_gate(self, tmp_path):
        notes_path = tmp_path / "research_notes.md"
        notes_path.write_text("# Research Notes\n\nFindings here.")
        sources_path = tmp_path / "research_sources.json"
        sources_path.write_text(json.dumps(["https://example.com/job"]))

        spec = AgentInvocationSpec(
            invocation_id="ainv_research",
            run_id="run_r",
            task_id="task_r",
            workspace_id="ws_r",
            agent_id="career-research-agent",
            skill_contract_version="career-research-v1",
            session_key="agent:career-research-agent:workspace:ws_r:run:run_r:task:task_r:attempt:1",
            input_spec_path=str(tmp_path / "input.json"),
            output_manifest_path=str(tmp_path / "output_manifest.json"),
            created_at=datetime.now(timezone.utc),
        )

        manifest = ResearchManifest(
            invocation_id="ainv_research",
            status="completed",
            stop_reason="all_questions_answered",
            artifact_paths={
                "research_notes": str(notes_path),
                "sources": str(sources_path),
            },
            job_id="job_abc",
            citations_count=1,
        )

        gate = ValidatorGate()
        results = gate.run(manifest, spec)
        assert gate.all_passed(results), [r.model_dump() for r in results if not r.passed]


# ---------------------------------------------------------------------------
# 5. Reflection manifest smoke test
# ---------------------------------------------------------------------------


class TestReflectionManifestSmoke:
    def test_valid_reflection_manifest_passes_gate(self, tmp_path):
        report_path = tmp_path / "reflection_report.md"
        report_path.write_text("# Reflection\n\nAnalysis here.")
        patch_path = tmp_path / "strategy_patch.json"
        patch_path.write_text(
            json.dumps({"run_id": "run_abc", "patches": []})
        )

        spec = AgentInvocationSpec(
            invocation_id="ainv_reflect",
            run_id="run_rf",
            task_id="task_rf",
            workspace_id="ws_rf",
            agent_id="career-reflect-agent",
            skill_contract_version="career-reflect-v1",
            session_key="agent:career-reflect-agent:workspace:ws_rf:run:run_rf:task:task_rf:attempt:1",
            input_spec_path=str(tmp_path / "input.json"),
            output_manifest_path=str(tmp_path / "output_manifest.json"),
            created_at=datetime.now(timezone.utc),
        )

        manifest = ReflectionManifest(
            invocation_id="ainv_reflect",
            status="completed",
            stop_reason="analysis_complete",
            artifact_paths={
                "reflection_report": str(report_path),
                "strategy_patch": str(patch_path),
            },
            run_id="run_abc",
            patches_proposed=0,
        )

        gate = ValidatorGate()
        results = gate.run(manifest, spec)
        assert gate.all_passed(results), [r.model_dump() for r in results if not r.passed]


# ---------------------------------------------------------------------------
# 6. build_invocation_spec smoke test
# ---------------------------------------------------------------------------


class TestBuildInvocationSpec:
    def test_spec_has_correct_agent_id_for_discovery(self, tmp_path):
        spec = build_invocation_spec(
            run_id="run_x",
            task_id="task_x",
            workspace_id="ws_x",
            task_type="agent.job_discovery",
            attempt=1,
            artifacts_base_dir=str(tmp_path),
            payload={},
        )
        assert spec.agent_id == "career-search-agent"
        assert spec.skill_contract_version == "career-search-v1"
        assert "agent.job_discovery" not in spec.session_key
        assert "career-search-agent" in spec.session_key

    def test_spec_has_correct_agent_id_for_research(self, tmp_path):
        spec = build_invocation_spec(
            run_id="run_x",
            task_id="task_x",
            workspace_id="ws_x",
            task_type="agent.job_research",
            attempt=1,
            artifacts_base_dir=str(tmp_path),
            payload={},
        )
        assert spec.agent_id == "career-research-agent"
        assert spec.skill_contract_version == "career-research-v1"

    def test_spec_has_correct_agent_id_for_reflection(self, tmp_path):
        spec = build_invocation_spec(
            run_id="run_x",
            task_id="task_x",
            workspace_id="ws_x",
            task_type="agent.run_reflection",
            attempt=1,
            artifacts_base_dir=str(tmp_path),
            payload={},
        )
        assert spec.agent_id == "career-reflect-agent"
        assert spec.skill_contract_version == "career-reflect-v1"

    def test_paths_are_inside_artifacts_dir(self, tmp_path):
        spec = build_invocation_spec(
            run_id="run_abc",
            task_id="task_xyz",
            workspace_id="ws_1",
            task_type="agent.job_discovery",
            attempt=1,
            artifacts_base_dir=str(tmp_path),
            payload={},
        )
        assert str(tmp_path) in spec.input_spec_path
        assert str(tmp_path) in spec.output_manifest_path
        assert "run_abc" in spec.input_spec_path
        assert "task_xyz" in spec.input_spec_path

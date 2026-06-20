"""
Contract tests for agent-related Pydantic models.
No IO — validates schema only.
"""

from __future__ import annotations

import pytest
from packages.contracts.agents.invocation import AgentBudget, AgentInvocationSpec, AgentTaskInput
from packages.contracts.agents.manifests import DiscoveryManifest, ResearchManifest
from packages.contracts.agents.validation import AgentValidationResult, ValidationError


def test_agent_budget_defaults():
    b = AgentBudget()
    assert b.max_tool_calls == 30
    assert b.timeout_seconds == 900


def test_agent_invocation_spec_required_fields():
    from datetime import datetime, timezone

    spec = AgentInvocationSpec(
        invocation_id="ainv_001",
        run_id="run_001",
        task_id="task_001",
        workspace_id="ws_001",
        agent_id="career-search-agent",
        skill_contract_version="career-search-v1",
        session_key="agent:career-search-agent:workspace:ws_001:run:run_001:task:task_001:attempt:1",
        input_spec_path="/tmp/input.json",
        output_manifest_path="/tmp/output_manifest.json",
        created_at=datetime.now(timezone.utc),
    )
    assert spec.timeout_seconds == 900
    assert spec.max_tool_calls == 30


def test_discovery_manifest_valid():
    manifest = DiscoveryManifest(
        invocation_id="ainv_001",
        status="completed",
        stop_reason="max_candidates_reached",
        artifact_paths={"candidate_pool": "/tmp/candidates.jsonl"},
        candidate_count=25,
        sources_tried=["greenhouse.io", "lever.co"],
        sources_added=["greenhouse.io"],
    )
    assert manifest.candidate_count == 25
    assert len(manifest.sources_tried) == 2


def test_discovery_manifest_partial_status():
    manifest = DiscoveryManifest(
        invocation_id="ainv_002",
        status="partial",
        stop_reason="timeout",
        candidate_count=5,
    )
    assert manifest.status == "partial"


def test_agent_validation_result_passed():
    result = AgentValidationResult(
        invocation_id="ainv_001",
        validator_name="schema",
        status="passed",
    )
    assert result.passed is True


def test_agent_validation_result_failed():
    result = AgentValidationResult(
        invocation_id="ainv_001",
        validator_name="provenance",
        status="failed",
        errors=[ValidationError(field="artifact_paths.candidate_pool", message="File missing")],
    )
    assert result.passed is False
    assert len(result.errors) == 1


def test_agent_validation_result_warning_still_passes():
    from packages.contracts.agents.validation import ValidationWarning

    result = AgentValidationResult(
        invocation_id="ainv_001",
        validator_name="schema",
        status="warning",
        warnings=[ValidationWarning(field="stop_reason", message="empty")],
    )
    assert result.passed is True

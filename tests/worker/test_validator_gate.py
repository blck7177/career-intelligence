"""
Unit tests for the Validator Gate and individual validators.
No IO — uses temp files and mocked manifests.
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from packages.contracts.agents.invocation import AgentInvocationSpec
from packages.contracts.agents.manifests import DiscoveryManifest
from packages.infrastructure.agent_runtime.validator import (
    BudgetValidator,
    ProvenanceValidator,
    SchemaValidator,
    ToolActivityValidator,
    ValidatorGate,
)


def make_spec(invocation_id: str = "ainv_test") -> AgentInvocationSpec:
    return AgentInvocationSpec(
        invocation_id=invocation_id,
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


def make_discovery_manifest(
    invocation_id: str = "ainv_test",
    status: str = "completed",
    artifact_paths: dict | None = None,
    candidate_count: int = 10,
) -> DiscoveryManifest:
    return DiscoveryManifest(
        invocation_id=invocation_id,
        status=status,
        stop_reason="max_candidates_reached",
        artifact_paths=artifact_paths or {},
        candidate_count=candidate_count,
        sources_tried=["source_a"],
    )


# ---------------------------------------------------------------------------
# SchemaValidator tests
# ---------------------------------------------------------------------------


class TestSchemaValidator:
    def setup_method(self):
        self.v = SchemaValidator()

    def test_passes_completed_manifest(self):
        spec = make_spec()
        manifest = make_discovery_manifest()
        result = self.v.validate(manifest, spec)
        assert result.status == "passed"

    def test_fails_when_agent_status_failed(self):
        spec = make_spec()
        manifest = make_discovery_manifest(status="failed")
        result = self.v.validate(manifest, spec)
        assert result.status == "failed"
        assert any("failure" in e.message.lower() for e in result.errors)

    def test_fails_when_invocation_id_mismatch(self):
        spec = make_spec("ainv_real")
        manifest = make_discovery_manifest(invocation_id="ainv_wrong")
        result = self.v.validate(manifest, spec)
        assert result.status == "failed"
        assert any("invocation_id" in e.field for e in result.errors)

    def test_warning_for_partial_status(self):
        spec = make_spec()
        manifest = make_discovery_manifest(status="partial")
        result = self.v.validate(manifest, spec)
        assert result.status == "warning"
        assert any("partial" in w.message.lower() for w in result.warnings)


# ---------------------------------------------------------------------------
# ProvenanceValidator tests
# ---------------------------------------------------------------------------


class TestProvenanceValidator:
    def setup_method(self):
        self.v = ProvenanceValidator()

    def test_passes_when_no_artifacts(self):
        spec = make_spec()
        manifest = make_discovery_manifest(artifact_paths={})
        result = self.v.validate(manifest, spec)
        assert result.status == "passed"

    def test_fails_when_artifact_file_missing(self):
        spec = make_spec()
        manifest = make_discovery_manifest(
            artifact_paths={"candidate_pool": "/nonexistent/path/candidates.jsonl"}
        )
        result = self.v.validate(manifest, spec)
        assert result.status == "failed"
        assert any("does not exist" in e.message for e in result.errors)

    def test_passes_with_valid_candidate_pool(self):
        spec = make_spec()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            for i in range(3):
                json.dump(
                    {"url": f"https://example.com/job/{i}", "title": f"Job {i}", "source_type": "ats"},
                    f,
                )
                f.write("\n")
            tmp_path = f.name

        manifest = make_discovery_manifest(artifact_paths={"candidate_pool": tmp_path})
        result = self.v.validate(manifest, spec)
        assert result.status == "passed"

    def test_fails_with_invalid_candidate_pool_json(self):
        spec = make_spec()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            f.write("not valid json\n")
            tmp_path = f.name

        manifest = make_discovery_manifest(artifact_paths={"candidate_pool": tmp_path})
        result = self.v.validate(manifest, spec)
        assert result.status == "failed"

    def test_fails_with_missing_required_fields_in_pool(self):
        spec = make_spec()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            json.dump({"url": "https://example.com/job/1"}, f)
            f.write("\n")
            tmp_path = f.name

        manifest = make_discovery_manifest(artifact_paths={"candidate_pool": tmp_path})
        result = self.v.validate(manifest, spec)
        assert result.status == "failed"
        assert any("Missing required fields" in e.message for e in result.errors)


# ---------------------------------------------------------------------------
# BudgetValidator tests
# ---------------------------------------------------------------------------


class TestBudgetValidator:
    def setup_method(self):
        self.v = BudgetValidator()

    def test_passes_normal_candidate_count(self):
        spec = make_spec()
        manifest = make_discovery_manifest(candidate_count=30)
        result = self.v.validate(manifest, spec)
        assert result.status == "passed"

    def test_warning_on_unusually_high_count(self):
        spec = make_spec()
        spec_with_low_budget = spec.model_copy(update={"max_tool_calls": 5})
        manifest = make_discovery_manifest(candidate_count=1000)
        result = self.v.validate(manifest, spec_with_low_budget)
        assert result.status == "warning"


# ---------------------------------------------------------------------------
# ToolActivityValidator tests
# ---------------------------------------------------------------------------


class TestToolActivityValidator:
    def setup_method(self):
        self.v = ToolActivityValidator()

    def test_passes_when_candidate_count_is_zero(self):
        """Valid no-yield run: no candidates, no trace needed."""
        spec = make_spec()
        manifest = make_discovery_manifest(candidate_count=0, artifact_paths={})
        result = self.v.validate(manifest, spec)
        assert result.status == "passed"

    def test_fails_when_candidates_but_no_trace_events(self):
        spec = make_spec()
        manifest = make_discovery_manifest(candidate_count=5, artifact_paths={})
        result = self.v.validate(manifest, spec)
        assert result.status == "failed"
        assert any("trace_events" in e.field for e in result.errors)

    def test_fails_when_trace_file_missing_on_disk(self, tmp_path):
        spec = make_spec()
        manifest = make_discovery_manifest(
            candidate_count=5,
            artifact_paths={"trace_events": str(tmp_path / "nonexistent.jsonl")},
        )
        result = self.v.validate(manifest, spec)
        assert result.status == "failed"
        assert any("does not exist" in e.message for e in result.errors)

    def test_fails_when_trace_has_no_discovery_tools(self, tmp_path):
        trace = tmp_path / "trace.jsonl"
        trace.write_text('{"event": "agent_started"}\n')
        spec = make_spec()
        manifest = make_discovery_manifest(
            candidate_count=5,
            artifact_paths={"trace_events": str(trace)},
        )
        result = self.v.validate(manifest, spec)
        assert result.status == "failed"
        assert any("no known discovery tool" in e.message for e in result.errors)

    def test_passes_with_web_search_in_trace(self, tmp_path):
        trace = tmp_path / "trace.jsonl"
        trace.write_text('{"tool": "web_search", "query": "risk analytics jobs"}\n')
        spec = make_spec()
        manifest = make_discovery_manifest(
            candidate_count=3,
            artifact_paths={"trace_events": str(trace)},
        )
        result = self.v.validate(manifest, spec)
        assert result.status == "passed"

    def test_passes_with_career_fetch_source_in_trace(self, tmp_path):
        trace = tmp_path / "trace.jsonl"
        trace.write_text('{"tool": "career_fetch_source", "url": "https://greenhouse.io/..."}\n')
        spec = make_spec()
        manifest = make_discovery_manifest(
            candidate_count=1,
            artifact_paths={"trace_events": str(trace)},
        )
        result = self.v.validate(manifest, spec)
        assert result.status == "passed"

    def test_passes_for_non_discovery_manifest(self):
        """ToolActivityValidator only applies to DiscoveryManifest."""
        from packages.contracts.agents.manifests import ResearchManifest
        from datetime import datetime, timezone

        spec = make_spec()
        manifest = ResearchManifest(
            invocation_id="ainv_test",
            status="completed",
            stop_reason="done",
            job_id="job_abc",
            citations_count=0,
        )
        result = self.v.validate(manifest, spec)
        assert result.status == "passed"


# ---------------------------------------------------------------------------
# ValidatorGate orchestration tests
# ---------------------------------------------------------------------------


class TestValidatorGate:
    def test_all_passed_returns_true_for_clean_manifest(self, tmp_path):
        """Clean manifest: has trace_events with real discovery activity."""
        trace = tmp_path / "trace_events.jsonl"
        trace.write_text('{"tool": "web_search", "query": "market risk roles"}\n')

        spec = make_spec()
        manifest = make_discovery_manifest(
            artifact_paths={"trace_events": str(trace)},
        )
        gate = ValidatorGate()
        results = gate.run(manifest, spec)
        assert gate.all_passed(results) is True, [
            r.model_dump() for r in results if not r.passed
        ]

    def test_all_passed_returns_true_for_zero_candidate_manifest(self):
        """Zero-candidate no-yield run: no trace required."""
        spec = make_spec()
        manifest = make_discovery_manifest(candidate_count=0, artifact_paths={})
        gate = ValidatorGate()
        results = gate.run(manifest, spec)
        assert gate.all_passed(results) is True

    def test_all_passed_returns_false_when_any_failed(self):
        spec = make_spec()
        manifest = make_discovery_manifest(status="failed")
        gate = ValidatorGate()
        results = gate.run(manifest, spec)
        assert gate.all_passed(results) is False

    def test_gate_does_not_raise_on_bad_validator(self):
        from packages.contracts.agents.validation import AgentValidationResult

        class BrokenValidator:
            name = "broken"

            def validate(self, manifest, spec):
                raise RuntimeError("intentional failure")

        spec = make_spec()
        manifest = make_discovery_manifest(candidate_count=0)
        gate = ValidatorGate(validators=[BrokenValidator()])  # type: ignore[arg-type]
        results = gate.run(manifest, spec)
        assert results[0].status == "failed"
        assert not gate.all_passed(results)

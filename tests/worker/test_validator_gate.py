"""
Unit tests for the Validator Gate and individual validators.
No IO — uses temp files and mocked manifests.

Key behaviour changes tested (validator v2):
  - stop_reason missing → SchemaValidator FAIL (was: warning)
  - ToolActivityValidator three-state gate:
      State A: no trace / no discovery tool → FAIL even when candidate_count==0
      State B: trace + discovery tool + no candidates → PASS (valid no-yield)
      State C: trace + discovery tool + candidates → PASS
  - ToolActivityValidator now also covers ResearchManifest (citations_count > 0)
  - ProvenanceValidator requires coverage_report artifact on non-failed discovery runs
  - New DiscoveryCountValidator: manifest.candidate_count must match pool line count
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from packages.contracts.agents.invocation import AgentInvocationSpec
from packages.contracts.agents.manifests import DiscoveryManifest, ResearchManifest
from packages.contracts.agents.tool_activity import ToolActivitySummary
from packages.infrastructure.agent_runtime.validator import (
    BudgetValidator,
    DiscoveryCountValidator,
    ProvenanceValidator,
    SchemaValidator,
    ToolActivityValidator,
    ValidatorGate,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


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
    stop_reason: str = "max_candidates_reached",
) -> DiscoveryManifest:
    return DiscoveryManifest(
        invocation_id=invocation_id,
        status=status,
        stop_reason=stop_reason,
        artifact_paths=artifact_paths or {},
        candidate_count=candidate_count,
        sources_tried=["source_a"],
    )


def write_trace(tmp_path: Path, tool_name: str) -> Path:
    """Write a minimal trace_events.jsonl containing one tool call."""
    trace = tmp_path / "trace_events.jsonl"
    trace.write_text(json.dumps({"tool": tool_name, "query": "test"}) + "\n")
    return trace


def write_pool(tmp_path: Path, count: int) -> Path:
    """Write a minimal candidate_pool.jsonl with `count` valid entries."""
    pool = tmp_path / "candidate_pool.jsonl"
    with pool.open("w") as f:
        for i in range(count):
            json.dump(
                {"url": f"https://example.com/job/{i}", "title": f"Job {i}", "source_type": "ats"},
                f,
            )
            f.write("\n")
    return pool


def write_coverage_report(tmp_path: Path) -> Path:
    report = tmp_path / "coverage_report.md"
    report.write_text("# Coverage\n\nSearched 5 queries across 3 boards.\n")
    return report


def write_gateway_summary(
    tmp_path: Path,
    *,
    invocation_id: str = "ainv_test",
    session_key: str = "agent:career-search-agent:workspace:ws_001:run:run_001:task:task_001:attempt:1",
    tools: list[str] | None = None,
    transport: str = "gateway",
    fallback_from: str | None = None,
) -> Path:
    tools = tools or []
    summary = ToolActivitySummary(
        invocation_id=invocation_id,
        session_key=session_key,
        transport=transport,
        fallback_from=fallback_from,
        tool_call_count=len(tools),
        tool_calls=[{"tool": t, "status": "succeeded"} for t in tools],
    )
    path = tmp_path / "gateway_tool_activity.json"
    path.write_text(summary.model_dump_json(indent=2))
    return path


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

    def test_fails_when_stop_reason_missing(self):
        """Missing stop_reason is now a hard error (v2 change)."""
        spec = make_spec()
        manifest = make_discovery_manifest(stop_reason="")
        result = self.v.validate(manifest, spec)
        assert result.status == "failed"
        assert any("stop_reason" in e.field for e in result.errors)


# ---------------------------------------------------------------------------
# ProvenanceValidator tests
# ---------------------------------------------------------------------------


class TestProvenanceValidator:
    def setup_method(self):
        self.v = ProvenanceValidator()

    def test_fails_when_no_coverage_report_for_completed_discovery(self):
        """coverage_report is required for non-failed discovery runs (v2)."""
        spec = make_spec()
        manifest = make_discovery_manifest(artifact_paths={})
        result = self.v.validate(manifest, spec)
        assert result.status == "failed"
        assert any("coverage_report" in e.field for e in result.errors)

    def test_passes_when_coverage_report_present(self, tmp_path):
        spec = make_spec()
        report = write_coverage_report(tmp_path)
        manifest = make_discovery_manifest(artifact_paths={"coverage_report": str(report)})
        result = self.v.validate(manifest, spec)
        assert result.status == "passed"

    def test_does_not_require_coverage_report_for_failed_status(self):
        """failed status is rejected by SchemaValidator; Provenance skips the requirement."""
        spec = make_spec()
        manifest = make_discovery_manifest(status="failed", artifact_paths={})
        result = self.v.validate(manifest, spec)
        # No coverage_report error — SchemaValidator handles the rejection.
        assert not any("coverage_report" in e.field for e in result.errors)

    def test_fails_when_artifact_file_missing(self, tmp_path):
        spec = make_spec()
        report = write_coverage_report(tmp_path)
        manifest = make_discovery_manifest(
            artifact_paths={
                "coverage_report": str(report),
                "candidate_pool": "/nonexistent/path/candidates.jsonl",
            }
        )
        result = self.v.validate(manifest, spec)
        assert result.status == "failed"
        assert any("does not exist" in e.message for e in result.errors)

    def test_passes_with_valid_candidate_pool(self, tmp_path):
        spec = make_spec()
        pool = write_pool(tmp_path, 3)
        report = write_coverage_report(tmp_path)
        manifest = make_discovery_manifest(
            artifact_paths={"candidate_pool": str(pool), "coverage_report": str(report)},
            candidate_count=3,
        )
        result = self.v.validate(manifest, spec)
        assert result.status == "passed"

    def test_fails_with_invalid_candidate_pool_json(self, tmp_path):
        spec = make_spec()
        pool = tmp_path / "pool.jsonl"
        pool.write_text("not valid json\n")
        report = write_coverage_report(tmp_path)
        manifest = make_discovery_manifest(
            artifact_paths={"candidate_pool": str(pool), "coverage_report": str(report)},
        )
        result = self.v.validate(manifest, spec)
        assert result.status == "failed"

    def test_fails_with_missing_required_fields_in_pool(self, tmp_path):
        spec = make_spec()
        pool = tmp_path / "pool.jsonl"
        pool.write_text(json.dumps({"url": "https://example.com/job/1"}) + "\n")
        report = write_coverage_report(tmp_path)
        manifest = make_discovery_manifest(
            artifact_paths={"candidate_pool": str(pool), "coverage_report": str(report)},
        )
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

    # --- Discovery: three-state gate ---

    def test_fails_state_a_zero_candidates_no_trace(self):
        """State A: zero discovery — completed run with no trace is rejected (v2)."""
        spec = make_spec()
        manifest = make_discovery_manifest(candidate_count=0, artifact_paths={})
        result = self.v.validate(manifest, spec)
        assert result.status == "failed"
        assert any("trace_events" in e.field for e in result.errors)

    def test_fails_state_a_partial_no_trace(self):
        """Partial run with no trace is also State A."""
        spec = make_spec()
        manifest = make_discovery_manifest(
            candidate_count=0, status="partial", artifact_paths={}
        )
        result = self.v.validate(manifest, spec)
        assert result.status == "failed"

    def test_passes_state_b_zero_candidates_with_trace(self, tmp_path):
        """State B: real search happened, nothing found — valid no-yield."""
        trace = write_trace(tmp_path, "web_search")
        spec = make_spec()
        manifest = make_discovery_manifest(
            candidate_count=0,
            artifact_paths={"trace_events": str(trace)},
        )
        result = self.v.validate(manifest, spec)
        assert result.status == "passed"

    def test_passes_state_c_candidates_with_trace(self, tmp_path):
        """State C: real search + candidates found."""
        trace = write_trace(tmp_path, "web_search")
        spec = make_spec()
        manifest = make_discovery_manifest(
            candidate_count=5,
            artifact_paths={"trace_events": str(trace)},
        )
        result = self.v.validate(manifest, spec)
        assert result.status == "passed"

    def test_state_a_not_checked_when_status_is_failed(self):
        """failed status manifest skips the activity gate (SchemaValidator handles it)."""
        spec = make_spec()
        manifest = make_discovery_manifest(
            candidate_count=0, status="failed", artifact_paths={}
        )
        result = self.v.validate(manifest, spec)
        # ToolActivityValidator passes — SchemaValidator is responsible for failed status.
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
        assert any("no evidence" in e.message.lower() for e in result.errors)

    def test_passes_with_web_search_in_trace(self, tmp_path):
        trace = write_trace(tmp_path, "web_search")
        spec = make_spec()
        manifest = make_discovery_manifest(
            candidate_count=3,
            artifact_paths={"trace_events": str(trace)},
        )
        result = self.v.validate(manifest, spec)
        assert result.status == "passed"

    def test_passes_with_career_fetch_source_in_trace(self, tmp_path):
        trace = write_trace(tmp_path, "career_fetch_source")
        spec = make_spec()
        manifest = make_discovery_manifest(
            candidate_count=1,
            artifact_paths={"trace_events": str(trace)},
        )
        result = self.v.validate(manifest, spec)
        assert result.status == "passed"

    # --- Research gate ---

    def test_passes_for_research_with_zero_citations(self):
        """Research run with no citations needs no tool evidence."""
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

    def test_fails_research_with_citations_but_no_trace(self):
        """Research manifest claiming citations but no tool evidence is rejected (v2)."""
        spec = make_spec()
        manifest = ResearchManifest(
            invocation_id="ainv_test",
            status="completed",
            stop_reason="done",
            job_id="job_abc",
            citations_count=3,
            artifact_paths={},
        )
        result = self.v.validate(manifest, spec)
        assert result.status == "failed"
        assert any("trace_events" in e.field for e in result.errors)

    def test_passes_research_with_citations_and_web_fetch_trace(self, tmp_path):
        trace = write_trace(tmp_path, "web_fetch")
        spec = make_spec()
        manifest = ResearchManifest(
            invocation_id="ainv_test",
            status="completed",
            stop_reason="done",
            job_id="job_abc",
            citations_count=3,
            artifact_paths={"trace_events": str(trace)},
        )
        result = self.v.validate(manifest, spec)
        assert result.status == "passed"

    def test_passes_research_with_citations_and_fetch_source_trace(self, tmp_path):
        trace = write_trace(tmp_path, "career_fetch_source")
        spec = make_spec()
        manifest = ResearchManifest(
            invocation_id="ainv_test",
            status="completed",
            stop_reason="done",
            job_id="job_abc",
            citations_count=1,
            artifact_paths={"trace_events": str(trace)},
        )
        result = self.v.validate(manifest, spec)
        assert result.status == "passed"

    def test_research_tool_check_skipped_when_status_failed(self):
        spec = make_spec()
        manifest = ResearchManifest(
            invocation_id="ainv_test",
            status="failed",
            stop_reason="error",
            job_id="job_abc",
            citations_count=3,
            artifact_paths={},
        )
        result = self.v.validate(manifest, spec)
        assert result.status == "passed"

    def test_discovery_can_pass_from_gateway_summary_without_trace(self, tmp_path):
        write_gateway_summary(tmp_path, tools=["web_search"])
        spec = make_spec().model_copy(
            update={"output_manifest_path": str(tmp_path / "output_manifest.json")}
        )
        manifest = make_discovery_manifest(candidate_count=0, artifact_paths={})
        result = self.v.validate(manifest, spec)
        assert result.status == "passed"

    def test_embedded_transport_in_gateway_summary_fails(self, tmp_path):
        write_gateway_summary(tmp_path, tools=["web_search"], transport="embedded")
        trace = write_trace(tmp_path, "web_search")
        spec = make_spec().model_copy(
            update={"output_manifest_path": str(tmp_path / "output_manifest.json")}
        )
        manifest = make_discovery_manifest(
            candidate_count=1,
            artifact_paths={"trace_events": str(trace)},
        )
        result = self.v.validate(manifest, spec)
        assert result.status == "failed"
        assert any("transport" in e.field for e in result.errors)


# ---------------------------------------------------------------------------
# DiscoveryCountValidator tests
# ---------------------------------------------------------------------------


class TestDiscoveryCountValidator:
    def setup_method(self):
        self.v = DiscoveryCountValidator()

    def test_passes_zero_count_no_pool(self):
        spec = make_spec()
        manifest = make_discovery_manifest(candidate_count=0, artifact_paths={})
        result = self.v.validate(manifest, spec)
        assert result.status == "passed"

    def test_passes_when_count_matches_pool_lines(self, tmp_path):
        pool = write_pool(tmp_path, 4)
        spec = make_spec()
        manifest = make_discovery_manifest(
            candidate_count=4,
            artifact_paths={"candidate_pool": str(pool)},
        )
        result = self.v.validate(manifest, spec)
        assert result.status == "passed"

    def test_fails_when_count_exceeds_pool_lines(self, tmp_path):
        pool = write_pool(tmp_path, 2)
        spec = make_spec()
        manifest = make_discovery_manifest(
            candidate_count=5,
            artifact_paths={"candidate_pool": str(pool)},
        )
        result = self.v.validate(manifest, spec)
        assert result.status == "failed"
        assert any("candidate_count" in e.field for e in result.errors)

    def test_fails_when_count_is_positive_but_no_pool(self):
        spec = make_spec()
        manifest = make_discovery_manifest(candidate_count=3, artifact_paths={})
        result = self.v.validate(manifest, spec)
        assert result.status == "failed"
        assert any("candidate_pool" in e.field for e in result.errors)

    def test_passes_non_discovery_manifest(self):
        spec = make_spec()
        manifest = ResearchManifest(
            invocation_id="ainv_test",
            status="completed",
            stop_reason="done",
            job_id="job_abc",
        )
        result = self.v.validate(manifest, spec)
        assert result.status == "passed"


# ---------------------------------------------------------------------------
# ValidatorGate orchestration tests
# ---------------------------------------------------------------------------


class TestValidatorGate:
    def _make_clean_discovery(self, tmp_path: Path) -> tuple[DiscoveryManifest, AgentInvocationSpec]:
        """Build a fully valid discovery manifest with all required artifacts."""
        trace = write_trace(tmp_path, "web_search")
        pool = write_pool(tmp_path, 3)
        report = write_coverage_report(tmp_path)
        spec = make_spec()
        manifest = make_discovery_manifest(
            candidate_count=3,
            artifact_paths={
                "trace_events": str(trace),
                "candidate_pool": str(pool),
                "coverage_report": str(report),
            },
        )
        return manifest, spec

    def test_all_passed_returns_true_for_clean_manifest(self, tmp_path):
        """Fully valid discovery manifest passes all gates."""
        manifest, spec = self._make_clean_discovery(tmp_path)
        gate = ValidatorGate()
        results = gate.run(manifest, spec)
        assert gate.all_passed(results) is True, [
            r.model_dump() for r in results if not r.passed
        ]

    def test_all_passed_returns_true_for_valid_no_yield(self, tmp_path):
        """State B: real search, no candidates — valid no-yield passes."""
        trace = write_trace(tmp_path, "web_search")
        report = write_coverage_report(tmp_path)
        spec = make_spec()
        manifest = make_discovery_manifest(
            candidate_count=0,
            artifact_paths={
                "trace_events": str(trace),
                "coverage_report": str(report),
            },
        )
        gate = ValidatorGate()
        results = gate.run(manifest, spec)
        assert gate.all_passed(results) is True, [
            r.model_dump() for r in results if not r.passed
        ]

    def test_fails_for_placeholder_state_a_run(self):
        """State A: no trace, no real work — gate must reject this (placeholder guard)."""
        spec = make_spec()
        manifest = make_discovery_manifest(
            candidate_count=0,
            artifact_paths={},
        )
        gate = ValidatorGate()
        results = gate.run(manifest, spec)
        assert gate.all_passed(results) is False
        failed_names = {r.validator_name for r in results if r.status == "failed"}
        assert "tool_activity" in failed_names

    def test_fails_for_partial_placeholder_with_no_trace(self):
        """Partial run with no real tool activity is rejected."""
        spec = make_spec()
        manifest = make_discovery_manifest(
            candidate_count=0,
            status="partial",
            stop_reason="Bounded test run with no live search",
            artifact_paths={},
        )
        gate = ValidatorGate()
        results = gate.run(manifest, spec)
        assert gate.all_passed(results) is False
        failed_names = {r.validator_name for r in results if r.status == "failed"}
        assert "tool_activity" in failed_names

    def test_all_passed_returns_false_when_any_failed(self):
        spec = make_spec()
        manifest = make_discovery_manifest(status="failed")
        gate = ValidatorGate()
        results = gate.run(manifest, spec)
        assert gate.all_passed(results) is False

    def test_gate_does_not_raise_on_bad_validator(self):
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

    def test_discovery_count_mismatch_fails_gate(self, tmp_path):
        """manifest.candidate_count != pool lines → gate rejects."""
        trace = write_trace(tmp_path, "web_search")
        pool = write_pool(tmp_path, 2)
        report = write_coverage_report(tmp_path)
        spec = make_spec()
        manifest = make_discovery_manifest(
            candidate_count=5,  # lies about count
            artifact_paths={
                "trace_events": str(trace),
                "candidate_pool": str(pool),
                "coverage_report": str(report),
            },
        )
        gate = ValidatorGate()
        results = gate.run(manifest, spec)
        assert gate.all_passed(results) is False
        failed_names = {r.validator_name for r in results if r.status == "failed"}
        assert "discovery_count" in failed_names

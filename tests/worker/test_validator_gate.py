"""
Unit tests for the Validator Gate and individual validators.
No IO — uses temp files and mocked manifests.

Key behaviour changes tested (validator v3):
  - stop_reason missing → SchemaValidator FAIL
  - GatewayTransportValidator: embedded/fallback transport → FAIL; absent file → PASS
  - ToolLedgerValidator: missing file → FAIL; bad sig → FAIL; broken chain → FAIL
  - DiscoveryEvidenceValidator: 0-result → FAIL; candidates with valid log → PASS
  - ProvenanceValidator requires coverage_report artifact on non-failed discovery runs
  - DiscoveryCountValidator: manifest.candidate_count must match pool line count
"""

from __future__ import annotations

import json
import os
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
    DiscoveryEvidenceValidator,
    GatewayTransportValidator,
    ProvenanceValidator,
    SchemaValidator,
    ToolLedgerValidator,
    ValidatorGate,
)
from packages.infrastructure.tool_ledger import append_signed_event, load_and_verify

_TEST_SIGNING_KEY = "test-signing-key-thats-at-least-32-bytes-long"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def make_spec(invocation_id: str = "ainv_test", tmp_path: Path | None = None) -> AgentInvocationSpec:
    manifest_path = str(tmp_path / "output_manifest.json") if tmp_path else "/tmp/output_manifest.json"
    return AgentInvocationSpec(
        invocation_id=invocation_id,
        run_id="run_001",
        task_id="task_001",
        workspace_id="ws_001",
        agent_id="career-search-agent",
        skill_contract_version="career-search-v1",
        session_key="agent:career-search-agent:workspace:ws_001:run:run_001:task:task_001:attempt:1",
        input_spec_path="/tmp/input.json",
        output_manifest_path=manifest_path,
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


def write_ledger(
    tmp_path: Path,
    *,
    invocation_id: str = "ainv_test",
    event_count: int = 1,
    signing_key: str = _TEST_SIGNING_KEY,
    candidate_count: int = 3,
    pool_path: Path | None = None,
) -> Path:
    """Write a valid signed tool_events.jsonl to tmp_path."""
    ledger = tmp_path / "tool_events.jsonl"
    pool_hash = None
    if pool_path and pool_path.exists():
        import hashlib
        pool_hash = "sha256:" + hashlib.sha256(pool_path.read_bytes()).hexdigest()

    for i in range(event_count):
        append_signed_event(
            ledger,
            {
                "invocation_id": invocation_id,
                "run_id": "run_001",
                "task_id": "task_001",
                "tool_name": "career_log_candidates",
                "event_type": "candidate_log",
                "status": "ok",
                "candidate_count": candidate_count,
                "output_path": str(pool_path) if pool_path else None,
                "output_hash": pool_hash,
            },
            signing_key,
        )
    return ledger


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
        """Missing stop_reason is a hard error."""
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
        spec = make_spec()
        manifest = make_discovery_manifest(status="failed", artifact_paths={})
        result = self.v.validate(manifest, spec)
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
# GatewayTransportValidator tests
# ---------------------------------------------------------------------------


class TestGatewayTransportValidator:
    def setup_method(self):
        self.v = GatewayTransportValidator()

    def test_passes_when_no_gateway_summary(self):
        """Absent gateway_tool_activity.json → pass (ledger is authoritative)."""
        spec = make_spec()
        manifest = make_discovery_manifest()
        result = self.v.validate(manifest, spec)
        assert result.status == "passed"

    def test_passes_with_valid_gateway_transport(self, tmp_path):
        write_gateway_summary(tmp_path, tools=["web_search"], transport="gateway")
        spec = make_spec(tmp_path=tmp_path)
        manifest = make_discovery_manifest()
        result = self.v.validate(manifest, spec)
        assert result.status == "passed"

    def test_fails_embedded_transport(self, tmp_path):
        write_gateway_summary(tmp_path, tools=["web_search"], transport="embedded")
        spec = make_spec(tmp_path=tmp_path)
        manifest = make_discovery_manifest()
        result = self.v.validate(manifest, spec)
        assert result.status == "failed"
        assert any("transport" in e.field for e in result.errors)

    def test_fails_fallback_from_gateway(self, tmp_path):
        write_gateway_summary(tmp_path, tools=["web_search"], fallback_from="gateway")
        spec = make_spec(tmp_path=tmp_path)
        manifest = make_discovery_manifest()
        result = self.v.validate(manifest, spec)
        assert result.status == "failed"
        assert any("fallback_from" in e.field for e in result.errors)


# ---------------------------------------------------------------------------
# ToolLedgerValidator tests
# ---------------------------------------------------------------------------


class TestToolLedgerValidator:
    def setup_method(self):
        self.v = ToolLedgerValidator()

    def test_ledger_validator_missing_file(self, tmp_path, monkeypatch):
        """Missing tool_events.jsonl → failed."""
        monkeypatch.setenv("TOOL_LEDGER_SIGNING_KEY", _TEST_SIGNING_KEY)
        spec = make_spec(tmp_path=tmp_path)
        manifest = make_discovery_manifest()
        result = self.v.validate(manifest, spec)
        assert result.status == "failed"
        assert any("not found" in e.message for e in result.errors)

    def test_ledger_validator_missing_key(self, tmp_path, monkeypatch):
        """Missing TOOL_LEDGER_SIGNING_KEY → failed (platform misconfiguration)."""
        monkeypatch.delenv("TOOL_LEDGER_SIGNING_KEY", raising=False)
        spec = make_spec(tmp_path=tmp_path)
        manifest = make_discovery_manifest()
        result = self.v.validate(manifest, spec)
        assert result.status == "failed"
        assert any("TOOL_LEDGER_SIGNING_KEY" in e.field for e in result.errors)

    def test_ledger_validator_valid_ledger_passes(self, tmp_path, monkeypatch):
        """Valid signed ledger → passed."""
        monkeypatch.setenv("TOOL_LEDGER_SIGNING_KEY", _TEST_SIGNING_KEY)
        pool = write_pool(tmp_path, 3)
        write_ledger(tmp_path, pool_path=pool, candidate_count=3)
        spec = make_spec(tmp_path=tmp_path)
        manifest = make_discovery_manifest()
        result = self.v.validate(manifest, spec)
        assert result.status == "passed"

    def test_ledger_validator_bad_signature(self, tmp_path, monkeypatch):
        """Tampered signature → failed."""
        monkeypatch.setenv("TOOL_LEDGER_SIGNING_KEY", _TEST_SIGNING_KEY)
        pool = write_pool(tmp_path, 3)
        ledger_path = tmp_path / "tool_events.jsonl"
        append_signed_event(
            ledger_path,
            {
                "invocation_id": "ainv_test",
                "run_id": "run_001",
                "task_id": "task_001",
                "tool_name": "career_log_candidates",
                "event_type": "candidate_log",
                "status": "ok",
                "candidate_count": 3,
                "output_path": str(pool),
            },
            _TEST_SIGNING_KEY,
        )
        # Tamper with the signature (Pydantic uses compact JSON — no space after colon)
        content = ledger_path.read_text()
        import re
        content = re.sub(r'"signature":\s*"[^"]*"', '"signature":"deadbeef"', content)
        ledger_path.write_text(content)

        spec = make_spec(tmp_path=tmp_path)
        manifest = make_discovery_manifest()
        result = self.v.validate(manifest, spec)
        assert result.status == "failed"
        assert any("signature" in e.message or "hash" in e.message for e in result.errors)

    def test_ledger_validator_broken_chain(self, tmp_path, monkeypatch):
        """Broken prev_event_hash chain → failed."""
        monkeypatch.setenv("TOOL_LEDGER_SIGNING_KEY", _TEST_SIGNING_KEY)
        pool = write_pool(tmp_path, 3)
        ledger_path = write_ledger(tmp_path, event_count=2, pool_path=pool, candidate_count=3)

        # Tamper with the second event's prev_event_hash
        lines = ledger_path.read_text().splitlines()
        import json as _json
        second = _json.loads(lines[1])
        second["prev_event_hash"] = "aaaa" * 16
        lines[1] = _json.dumps(second)
        ledger_path.write_text("\n".join(lines) + "\n")

        spec = make_spec(tmp_path=tmp_path)
        manifest = make_discovery_manifest()
        result = self.v.validate(manifest, spec)
        assert result.status == "failed"
        assert any("chain" in e.message or "signature" in e.message for e in result.errors)

    def test_ledger_validator_wrong_invocation_id(self, tmp_path, monkeypatch):
        """Ledger contains only events for a different invocation → no events found → not failed by this validator (chain is empty)."""
        monkeypatch.setenv("TOOL_LEDGER_SIGNING_KEY", _TEST_SIGNING_KEY)
        pool = write_pool(tmp_path, 3)
        # Write ledger for a DIFFERENT invocation
        append_signed_event(
            tmp_path / "tool_events.jsonl",
            {
                "invocation_id": "ainv_other",
                "run_id": "run_001",
                "task_id": "task_001",
                "tool_name": "career_log_candidates",
                "event_type": "candidate_log",
                "status": "ok",
                "candidate_count": 3,
            },
            _TEST_SIGNING_KEY,
        )
        spec = make_spec(tmp_path=tmp_path)  # invocation_id = "ainv_test"
        manifest = make_discovery_manifest()
        # File exists, no events for this invocation → passes ToolLedgerValidator
        # (DiscoveryEvidenceValidator will catch the missing log evidence)
        result = self.v.validate(manifest, spec)
        assert result.status == "passed"

    def test_ledger_validator_non_discovery_manifest_passes(self, tmp_path, monkeypatch):
        """Non-discovery manifests are skipped by ToolLedgerValidator."""
        monkeypatch.setenv("TOOL_LEDGER_SIGNING_KEY", _TEST_SIGNING_KEY)
        spec = make_spec(tmp_path=tmp_path)
        manifest = ResearchManifest(
            invocation_id="ainv_test",
            status="completed",
            stop_reason="done",
            job_id="job_abc",
        )
        result = self.v.validate(manifest, spec)
        assert result.status == "passed"


# ---------------------------------------------------------------------------
# DiscoveryEvidenceValidator tests
# ---------------------------------------------------------------------------


class TestDiscoveryEvidenceValidator:
    def setup_method(self):
        self.v = DiscoveryEvidenceValidator()

    def test_discovery_evidence_zero_candidates(self, tmp_path, monkeypatch):
        """0-result run: no signed search proof in v1 → failed."""
        monkeypatch.setenv("TOOL_LEDGER_SIGNING_KEY", _TEST_SIGNING_KEY)
        pool = write_pool(tmp_path, 0)
        write_ledger(tmp_path, pool_path=pool, candidate_count=0)
        spec = make_spec(tmp_path=tmp_path)
        manifest = make_discovery_manifest(candidate_count=0)
        result = self.v.validate(manifest, spec)
        assert result.status == "failed"
        assert any("0-result" in e.message for e in result.errors)

    def test_discovery_evidence_no_candidates_no_signed_log(self, tmp_path, monkeypatch):
        """Candidates > 0 but no ledger file → failed (State A)."""
        monkeypatch.setenv("TOOL_LEDGER_SIGNING_KEY", _TEST_SIGNING_KEY)
        spec = make_spec(tmp_path=tmp_path)
        manifest = make_discovery_manifest(candidate_count=5)
        result = self.v.validate(manifest, spec)
        assert result.status == "failed"
        assert any("candidate_log" in e.message for e in result.errors)

    def test_discovery_evidence_candidates_valid_log(self, tmp_path, monkeypatch):
        """Candidates > 0 with valid signed candidate_log → passed (State C)."""
        monkeypatch.setenv("TOOL_LEDGER_SIGNING_KEY", _TEST_SIGNING_KEY)
        pool = write_pool(tmp_path, 3)
        write_ledger(tmp_path, pool_path=pool, candidate_count=3)
        spec = make_spec(tmp_path=tmp_path)
        manifest = make_discovery_manifest(
            candidate_count=3,
            artifact_paths={"candidate_pool": str(pool)},
        )
        result = self.v.validate(manifest, spec)
        assert result.status == "passed"

    def test_discovery_evidence_log_hash_mismatch(self, tmp_path, monkeypatch):
        """Pool file tampered after logging → hash mismatch → failed."""
        monkeypatch.setenv("TOOL_LEDGER_SIGNING_KEY", _TEST_SIGNING_KEY)
        pool = write_pool(tmp_path, 3)
        write_ledger(tmp_path, pool_path=pool, candidate_count=3)
        # Tamper with pool after signing
        with pool.open("a") as f:
            f.write(json.dumps({"url": "https://evil.com/job/9", "title": "Ghost", "source_type": "ats"}) + "\n")

        spec = make_spec(tmp_path=tmp_path)
        manifest = make_discovery_manifest(
            candidate_count=3,
            artifact_paths={"candidate_pool": str(pool)},
        )
        result = self.v.validate(manifest, spec)
        assert result.status == "failed"
        assert any("hash" in e.message for e in result.errors)

    def test_discovery_evidence_skipped_for_failed_status(self, tmp_path, monkeypatch):
        """Failed manifests are not checked by DiscoveryEvidenceValidator."""
        monkeypatch.setenv("TOOL_LEDGER_SIGNING_KEY", _TEST_SIGNING_KEY)
        spec = make_spec(tmp_path=tmp_path)
        manifest = make_discovery_manifest(candidate_count=5, status="failed")
        result = self.v.validate(manifest, spec)
        assert result.status == "passed"

    def test_discovery_evidence_non_discovery_manifest_passes(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TOOL_LEDGER_SIGNING_KEY", _TEST_SIGNING_KEY)
        spec = make_spec(tmp_path=tmp_path)
        manifest = ResearchManifest(
            invocation_id="ainv_test",
            status="completed",
            stop_reason="done",
            job_id="job_abc",
        )
        result = self.v.validate(manifest, spec)
        assert result.status == "passed"


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
    def _make_clean_discovery(
        self, tmp_path: Path, monkeypatch
    ) -> tuple[DiscoveryManifest, AgentInvocationSpec]:
        """Build a fully valid discovery manifest with all required artifacts."""
        monkeypatch.setenv("TOOL_LEDGER_SIGNING_KEY", _TEST_SIGNING_KEY)
        pool = write_pool(tmp_path, 3)
        report = write_coverage_report(tmp_path)
        write_ledger(tmp_path, pool_path=pool, candidate_count=3)
        spec = make_spec(tmp_path=tmp_path)
        manifest = make_discovery_manifest(
            candidate_count=3,
            artifact_paths={
                "candidate_pool": str(pool),
                "coverage_report": str(report),
            },
        )
        return manifest, spec

    def test_all_passed_returns_true_for_clean_manifest(self, tmp_path, monkeypatch):
        """Fully valid discovery manifest passes all gates."""
        manifest, spec = self._make_clean_discovery(tmp_path, monkeypatch)
        gate = ValidatorGate()
        results = gate.run(manifest, spec)
        assert gate.all_passed(results) is True, [
            r.model_dump() for r in results if not r.passed
        ]

    def test_fails_for_state_a_no_ledger(self, tmp_path, monkeypatch):
        """No tool_events.jsonl → ToolLedgerValidator fails."""
        monkeypatch.setenv("TOOL_LEDGER_SIGNING_KEY", _TEST_SIGNING_KEY)
        spec = make_spec(tmp_path=tmp_path)
        manifest = make_discovery_manifest(
            candidate_count=0,
            artifact_paths={},
        )
        gate = ValidatorGate()
        results = gate.run(manifest, spec)
        assert gate.all_passed(results) is False
        failed_names = {r.validator_name for r in results if r.status == "failed"}
        assert "tool_ledger" in failed_names

    def test_fails_when_any_validator_fails(self):
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

    def test_discovery_count_mismatch_fails_gate(self, tmp_path, monkeypatch):
        """manifest.candidate_count != pool lines → gate rejects."""
        monkeypatch.setenv("TOOL_LEDGER_SIGNING_KEY", _TEST_SIGNING_KEY)
        pool = write_pool(tmp_path, 2)
        report = write_coverage_report(tmp_path)
        write_ledger(tmp_path, pool_path=pool, candidate_count=2)
        spec = make_spec(tmp_path=tmp_path)
        manifest = make_discovery_manifest(
            candidate_count=5,  # lies about count
            artifact_paths={
                "candidate_pool": str(pool),
                "coverage_report": str(report),
            },
        )
        gate = ValidatorGate()
        results = gate.run(manifest, spec)
        assert gate.all_passed(results) is False
        failed_names = {r.validator_name for r in results if r.status == "failed"}
        assert "discovery_count" in failed_names

    def test_embedded_transport_fails_gate(self, tmp_path, monkeypatch):
        """Embedded transport in gateway summary → gate rejects."""
        monkeypatch.setenv("TOOL_LEDGER_SIGNING_KEY", _TEST_SIGNING_KEY)
        write_gateway_summary(tmp_path, tools=["web_search"], transport="embedded")
        pool = write_pool(tmp_path, 3)
        report = write_coverage_report(tmp_path)
        write_ledger(tmp_path, pool_path=pool, candidate_count=3)
        spec = make_spec(tmp_path=tmp_path)
        manifest = make_discovery_manifest(
            candidate_count=3,
            artifact_paths={
                "candidate_pool": str(pool),
                "coverage_report": str(report),
            },
        )
        gate = ValidatorGate()
        results = gate.run(manifest, spec)
        assert gate.all_passed(results) is False
        failed_names = {r.validator_name for r in results if r.status == "failed"}
        assert "gateway_transport" in failed_names

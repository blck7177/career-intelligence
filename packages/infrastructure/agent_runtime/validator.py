"""
Validator Gate v2 — schema + provenance + budget + tool-activity + count checks.

Flow:
  Worker calls ValidatorGate.run(manifest, spec) after reading output_manifest.json.
  Each validator returns an AgentValidationResult.
  If any result has status == "failed", the gate rejects the output:
    - task.status → needs_review
    - No writes to jobs/artifacts tables
    - validation results written to agent_validation_results table

Rules:
  - Validators are stateless; they do not write to DB.
  - Validators must not raise — return a "failed" result instead.
  - New validators can be added without changing the gate interface.

Three-state discovery provenance gate (from AGENT_IO_CONTRACT.md):
  A — no discovery : discovery actions == 0 AND no evidence  → FAIL
  B — valid no-yield: discovery actions > 0, candidates == 0 → PASS (empty pool)
  C — candidates    : discovery actions > 0, candidates > 0  → PASS (normal run)
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path

from packages.contracts.agents.invocation import AgentInvocationSpec
from packages.contracts.agents.manifests import (
    AgentOutputManifest,
    DiscoveryManifest,
    ResearchManifest,
)
from packages.contracts.agents.tool_activity import ToolActivitySummary
from packages.contracts.agents.validation import (
    AgentValidationResult,
    ValidationError,
    ValidationWarning,
)

logger = logging.getLogger(__name__)

_TOOL_ACTIVITY_SUMMARY_FILENAME = "gateway_tool_activity.json"


# ---------------------------------------------------------------------------
# Validator interface
# ---------------------------------------------------------------------------


class Validator(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def validate(
        self,
        manifest: AgentOutputManifest,
        spec: AgentInvocationSpec,
    ) -> AgentValidationResult: ...


# ---------------------------------------------------------------------------
# Schema validator
# ---------------------------------------------------------------------------


class SchemaValidator(Validator):
    """
    Checks that the manifest has required fields and a non-failed status.

    `status == "partial"` is a warning (the downstream pipeline may accept it
    depending on task type), but ToolActivityValidator and ProvenanceValidator
    will independently fail zero-evidence partial runs.
    """

    name = "schema"

    def validate(
        self,
        manifest: AgentOutputManifest,
        spec: AgentInvocationSpec,
    ) -> AgentValidationResult:
        errors: list[ValidationError] = []
        warnings: list[ValidationWarning] = []

        if manifest.status == "failed":
            errors.append(
                ValidationError(
                    field="status",
                    message="Agent reported failure status",
                    value=manifest.status,
                )
            )

        if not manifest.invocation_id:
            errors.append(
                ValidationError(field="invocation_id", message="invocation_id is missing")
            )
        elif manifest.invocation_id != spec.invocation_id:
            errors.append(
                ValidationError(
                    field="invocation_id",
                    message="Manifest invocation_id does not match spec",
                    value=manifest.invocation_id,
                )
            )

        if not manifest.stop_reason:
            errors.append(
                ValidationError(
                    field="stop_reason",
                    message="stop_reason is missing — agent must document why it stopped",
                )
            )

        if manifest.status == "partial":
            warnings.append(
                ValidationWarning(
                    field="status",
                    message="Agent reported partial completion — review artifacts before persisting",
                )
            )

        status = "failed" if errors else ("warning" if warnings else "passed")
        return AgentValidationResult(
            invocation_id=spec.invocation_id,
            validator_name=self.name,
            status=status,
            errors=errors,
            warnings=warnings,
        )


# ---------------------------------------------------------------------------
# Provenance validator
# ---------------------------------------------------------------------------


class ProvenanceValidator(Validator):
    """
    Checks that declared artifact files exist on disk and are non-empty.

    For discovery manifests, also:
      - Requires a ``coverage_report`` artifact on non-failed runs.
      - Validates candidate_pool.jsonl line structure.
    """

    name = "provenance"

    def validate(
        self,
        manifest: AgentOutputManifest,
        spec: AgentInvocationSpec,
    ) -> AgentValidationResult:
        errors: list[ValidationError] = []
        warnings: list[ValidationWarning] = []

        for artifact_type, path_str in manifest.artifact_paths.items():
            path = Path(path_str)
            if not path.exists():
                errors.append(
                    ValidationError(
                        field=f"artifact_paths.{artifact_type}",
                        message=f"Artifact file does not exist: {path_str}",
                        value=path_str,
                    )
                )
                continue
            if path.stat().st_size == 0:
                warnings.append(
                    ValidationWarning(
                        field=f"artifact_paths.{artifact_type}",
                        message=f"Artifact file is empty: {path_str}",
                    )
                )

        if isinstance(manifest, DiscoveryManifest):
            errors.extend(self._check_discovery(manifest))

        status = "failed" if errors else ("warning" if warnings else "passed")
        return AgentValidationResult(
            invocation_id=spec.invocation_id,
            validator_name=self.name,
            status=status,
            errors=errors,
            warnings=warnings,
        )

    def _check_discovery(self, manifest: DiscoveryManifest) -> list[ValidationError]:
        errors: list[ValidationError] = []

        # coverage_report is mandatory on non-failed runs (SKILL.md completion gate)
        if manifest.status != "failed":
            if "coverage_report" not in manifest.artifact_paths:
                errors.append(
                    ValidationError(
                        field="artifact_paths.coverage_report",
                        message=(
                            "coverage_report artifact is missing — "
                            "skill requires writing coverage_report.md before stopping"
                        ),
                    )
                )

        # Validate candidate_pool.jsonl line structure
        pool_path_str = manifest.artifact_paths.get("candidate_pool")
        if pool_path_str:
            pool_path = Path(pool_path_str)
            if pool_path.exists() and pool_path.stat().st_size > 0:
                errors.extend(self._check_candidate_pool(pool_path))

        return errors

    def _check_candidate_pool(self, path: Path) -> list[ValidationError]:
        errors: list[ValidationError] = []
        required_fields = {"url", "title", "source_type"}
        try:
            with path.open() as f:
                for i, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError as exc:
                        errors.append(
                            ValidationError(
                                field=f"candidate_pool[{i}]",
                                message=f"Invalid JSON: {exc}",
                            )
                        )
                        continue
                    missing = required_fields - set(record.keys())
                    if missing:
                        errors.append(
                            ValidationError(
                                field=f"candidate_pool[{i}]",
                                message=f"Missing required fields: {missing}",
                            )
                        )
                    if i > 500:
                        break
        except OSError as exc:
            errors.append(
                ValidationError(
                    field="candidate_pool",
                    message=f"Could not read file: {exc}",
                )
            )
        return errors


# ---------------------------------------------------------------------------
# Budget validator
# ---------------------------------------------------------------------------


class BudgetValidator(Validator):
    """
    Checks that the agent stayed within declared budget limits.
    """

    name = "budget"

    def validate(
        self,
        manifest: AgentOutputManifest,
        spec: AgentInvocationSpec,
    ) -> AgentValidationResult:
        errors: list[ValidationError] = []
        warnings: list[ValidationWarning] = []

        if isinstance(manifest, DiscoveryManifest):
            if manifest.candidate_count > spec.max_tool_calls * 10:
                warnings.append(
                    ValidationWarning(
                        field="candidate_count",
                        message=(
                            f"Unusually high candidate count ({manifest.candidate_count}) "
                            f"relative to max_tool_calls ({spec.max_tool_calls})"
                        ),
                    )
                )

        status = "failed" if errors else ("warning" if warnings else "passed")
        return AgentValidationResult(
            invocation_id=spec.invocation_id,
            validator_name=self.name,
            status=status,
            errors=errors,
            warnings=warnings,
        )


# ---------------------------------------------------------------------------
# Tool activity validator
# ---------------------------------------------------------------------------


class ToolActivityValidator(Validator):
    """
    Guards against phantom outputs — runs that report results without any real
    tool activity.

    Discovery three-state gate (AGENT_IO_CONTRACT.md):
      State A — FAIL:  no discovery evidence at all (zero searches, no trace)
      State B — PASS:  real discovery actions ran but found nothing (empty pool)
      State C — PASS:  real discovery actions ran and found candidates

    A "failed" status discovery manifest is already caught by SchemaValidator
    and is not re-checked here.

    Research gate:
      citations_count > 0 requires evidence of real web_fetch or
      career_fetch_source calls in trace_events.
    """

    name = "tool_activity"

    DISCOVERY_TOOLS = frozenset(
        {
            "web_search",
            "web_fetch",
            "career_fetch_source",
            "career_log_candidates",
        }
    )

    RESEARCH_TOOLS = frozenset(
        {
            "web_fetch",
            "career_fetch_source",
        }
    )

    def validate(
        self,
        manifest: AgentOutputManifest,
        spec: AgentInvocationSpec,
    ) -> AgentValidationResult:
        errors: list[ValidationError] = []
        warnings: list[ValidationWarning] = []
        summary = self._load_gateway_summary(spec)

        if isinstance(manifest, DiscoveryManifest):
            errors.extend(self._validate_discovery(manifest, summary))
        elif isinstance(manifest, ResearchManifest):
            errors.extend(self._validate_research(manifest, summary))
        # ReflectionManifest has no tool activity requirement here.

        status = "failed" if errors else ("warning" if warnings else "passed")
        return AgentValidationResult(
            invocation_id=spec.invocation_id,
            validator_name=self.name,
            status=status,
            errors=errors,
            warnings=warnings,
        )

    def _validate_discovery(
        self,
        manifest: DiscoveryManifest,
        summary: ToolActivitySummary | None,
    ) -> list[ValidationError]:
        # "failed" status is already rejected by SchemaValidator; no further
        # tool-activity check needed for an explicitly-failed run.
        if manifest.status == "failed":
            return []

        if summary is not None:
            return self._validate_discovery_with_summary(manifest, summary)
        return self._validate_discovery_with_trace(manifest)

    def _validate_discovery_with_summary(
        self,
        manifest: DiscoveryManifest,
        summary: ToolActivitySummary,
    ) -> list[ValidationError]:
        transport_errors = self._validate_transport(summary)
        if transport_errors:
            return transport_errors

        called_tools = {c.tool for c in summary.tool_calls}
        if called_tools & self.DISCOVERY_TOOLS:
            return []
        return [
            ValidationError(
                field="gateway_tool_activity",
                message=(
                    "gateway_tool_activity shows no discovery calls for this run "
                    f"(expected one of: {sorted(self.DISCOVERY_TOOLS)}). "
                    "State A runs (zero searches) are not accepted as valid no-yield"
                ),
            )
        ]

    def _validate_discovery_with_trace(
        self,
        manifest: DiscoveryManifest,
    ) -> list[ValidationError]:
        trace_path_str = manifest.artifact_paths.get("trace_events")

        # No trace at all → State A: zero discovery (both 0-candidate and n-candidate)
        if not trace_path_str:
            return [
                ValidationError(
                    field="artifact_paths.trace_events",
                    message=(
                        "trace_events artifact is missing — "
                        "at least one real discovery action is required "
                        "(web_search, web_fetch, or an approved wrapper); "
                        "placeholder / mock output is not accepted"
                    ),
                )
            ]

        trace_path = Path(trace_path_str)
        if not trace_path.exists():
            return [
                ValidationError(
                    field="artifact_paths.trace_events",
                    message=(
                        f"trace_events file does not exist: {trace_path_str} — "
                        "at least one real discovery action is required"
                    ),
                    value=trace_path_str,
                )
            ]

        found_tool = self._file_contains_any(trace_path, self.DISCOVERY_TOOLS)
        if not found_tool:
            return [
                ValidationError(
                    field="artifact_paths.trace_events",
                    message=(
                        "trace_events contains no evidence of a real discovery tool call "
                        f"(looked for: {sorted(self.DISCOVERY_TOOLS)}); "
                        "State A runs (zero searches) are not accepted as valid no-yield"
                    ),
                )
            ]

        # trace contains evidence → State B (0 candidates) or State C (n candidates)
        return []

    def _validate_research(
        self,
        manifest: ResearchManifest,
        summary: ToolActivitySummary | None,
    ) -> list[ValidationError]:
        # Only enforce tool-activity when the agent claims it found something.
        if manifest.citations_count == 0:
            return []
        if manifest.status == "failed":
            return []

        if summary is not None:
            return self._validate_research_with_summary(manifest, summary)
        return self._validate_research_with_trace(manifest)

    def _validate_research_with_summary(
        self,
        manifest: ResearchManifest,
        summary: ToolActivitySummary,
    ) -> list[ValidationError]:
        transport_errors = self._validate_transport(summary)
        if transport_errors:
            return transport_errors

        called_tools = {c.tool for c in summary.tool_calls}
        if called_tools & self.RESEARCH_TOOLS:
            return []
        return [
            ValidationError(
                field="gateway_tool_activity",
                message=(
                    f"citations_count={manifest.citations_count} but "
                    "gateway_tool_activity shows no web_fetch/career_fetch_source "
                    "calls — research results without real fetch calls are not accepted"
                ),
            )
        ]

    def _validate_research_with_trace(
        self,
        manifest: ResearchManifest,
    ) -> list[ValidationError]:
        trace_path_str = manifest.artifact_paths.get("trace_events")

        if not trace_path_str:
            return [
                ValidationError(
                    field="artifact_paths.trace_events",
                    message=(
                        f"citations_count={manifest.citations_count} but "
                        "trace_events artifact is missing — "
                        "research results require evidence of real web_fetch calls"
                    ),
                )
            ]

        trace_path = Path(trace_path_str)
        if not trace_path.exists():
            return [
                ValidationError(
                    field="artifact_paths.trace_events",
                    message=(
                        f"citations_count={manifest.citations_count} but "
                        f"trace_events file does not exist: {trace_path_str}"
                    ),
                    value=trace_path_str,
                )
            ]

        found_tool = self._file_contains_any(trace_path, self.RESEARCH_TOOLS)
        if not found_tool:
            return [
                ValidationError(
                    field="artifact_paths.trace_events",
                    message=(
                        f"citations_count={manifest.citations_count} but "
                        "trace_events contains no evidence of web_fetch or "
                        "career_fetch_source — research results without real "
                        "fetch calls are not accepted"
                    ),
                )
            ]

        return []

    @staticmethod
    def _load_gateway_summary(spec: AgentInvocationSpec) -> ToolActivitySummary | None:
        summary_path = Path(spec.output_manifest_path).parent / _TOOL_ACTIVITY_SUMMARY_FILENAME
        if not summary_path.exists():
            return None
        try:
            return ToolActivitySummary.model_validate_json(summary_path.read_text())
        except Exception as exc:
            logger.warning(
                "Failed to parse gateway tool activity summary (%s): %s",
                summary_path,
                exc,
            )
            return None

    @staticmethod
    def _validate_transport(summary: ToolActivitySummary) -> list[ValidationError]:
        transport = (summary.transport or "").lower()
        fallback_from = (summary.fallback_from or "").lower()
        if transport == "embedded":
            return [
                ValidationError(
                    field="gateway_tool_activity.transport",
                    message=(
                        "gateway_tool_activity indicates embedded transport; "
                        "gateway-only runs must not use embedded mode"
                    ),
                    value=summary.transport,
                )
            ]
        if fallback_from == "gateway":
            return [
                ValidationError(
                    field="gateway_tool_activity.fallback_from",
                    message=(
                        "gateway_tool_activity indicates fallbackFrom=gateway; "
                        "fallback to embedded runtime is not accepted"
                    ),
                    value=summary.fallback_from,
                )
            ]
        return []

    @staticmethod
    def _file_contains_any(path: Path, needles: frozenset[str]) -> bool:
        """Return True if the file content contains any of the needle strings."""
        try:
            content = path.read_text()
            return any(needle in content for needle in needles)
        except OSError:
            return False


# ---------------------------------------------------------------------------
# Discovery count consistency validator
# ---------------------------------------------------------------------------


class DiscoveryCountValidator(Validator):
    """
    Verifies that manifest.candidate_count matches the actual number of
    non-empty lines in candidate_pool.jsonl.

    Prevents the agent from self-reporting a count that differs from what
    it actually wrote to the pool file.
    """

    name = "discovery_count"

    def validate(
        self,
        manifest: AgentOutputManifest,
        spec: AgentInvocationSpec,
    ) -> AgentValidationResult:
        errors: list[ValidationError] = []
        warnings: list[ValidationWarning] = []

        if not isinstance(manifest, DiscoveryManifest):
            return AgentValidationResult(
                invocation_id=spec.invocation_id,
                validator_name=self.name,
                status="passed",
                errors=[],
                warnings=[],
            )

        reported = manifest.candidate_count
        pool_path_str = manifest.artifact_paths.get("candidate_pool")

        if reported == 0 and not pool_path_str:
            # Zero candidates with no pool file is consistent.
            status = "passed"
        elif reported > 0 and not pool_path_str:
            errors.append(
                ValidationError(
                    field="artifact_paths.candidate_pool",
                    message=(
                        f"candidate_count={reported} but candidate_pool artifact "
                        "is missing from manifest"
                    ),
                )
            )
            status = "failed"
        else:
            actual = self._count_pool_lines(pool_path_str)  # type: ignore[arg-type]
            if actual is None:
                # File missing or unreadable — ProvenanceValidator will catch this
                status = "passed"
            elif actual != reported:
                errors.append(
                    ValidationError(
                        field="candidate_count",
                        message=(
                            f"manifest reports candidate_count={reported} but "
                            f"candidate_pool.jsonl has {actual} non-empty lines"
                        ),
                        value=str(reported),
                    )
                )
                status = "failed"
            else:
                status = "passed"

        return AgentValidationResult(
            invocation_id=spec.invocation_id,
            validator_name=self.name,
            status=status,
            errors=errors,
            warnings=warnings,
        )

    @staticmethod
    def _count_pool_lines(path_str: str) -> int | None:
        """Count non-empty lines in a .jsonl file. Returns None if unreadable."""
        path = Path(path_str)
        if not path.exists():
            return None
        try:
            count = 0
            with path.open() as f:
                for line in f:
                    if line.strip():
                        count += 1
            return count
        except OSError:
            return None


# ---------------------------------------------------------------------------
# Gate orchestrator
# ---------------------------------------------------------------------------


class ValidatorGate:
    """
    Runs all validators in sequence and returns consolidated results.

    Usage:
        gate = ValidatorGate()
        results = gate.run(manifest, spec)
        if gate.all_passed(results):
            # write to Postgres
        else:
            # write needs_review + agent_validation_results
    """

    def __init__(self, validators: list[Validator] | None = None) -> None:
        self._validators: list[Validator] = validators or [
            SchemaValidator(),
            ProvenanceValidator(),
            BudgetValidator(),
            ToolActivityValidator(),
            DiscoveryCountValidator(),
        ]

    def run(
        self,
        manifest: AgentOutputManifest,
        spec: AgentInvocationSpec,
    ) -> list[AgentValidationResult]:
        results: list[AgentValidationResult]= []
        for v in self._validators:
            try:
                result = v.validate(manifest, spec)
            except Exception as exc:
                logger.exception("Validator %s raised unexpectedly: %s", v.name, exc)
                result = AgentValidationResult(
                    invocation_id=spec.invocation_id,
                    validator_name=v.name,
                    status="failed",
                    errors=[
                        ValidationError(
                            field="_internal",
                            message=f"Validator raised: {exc}",
                        )
                    ],
                )
            results.append(result)
            if result.status == "failed":
                logger.warning(
                    "Validator %s FAILED for invocation %s: %s",
                    v.name,
                    spec.invocation_id,
                    [e.message for e in result.errors],
                )
            else:
                logger.info(
                    "Validator %s passed for invocation %s (status=%s)",
                    v.name,
                    spec.invocation_id,
                    result.status,
                )
        return results

    def all_passed(self, results: list[AgentValidationResult]) -> bool:
        return all(r.passed for r in results)

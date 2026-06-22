"""
Validator Gate v3 — schema + provenance + budget + gateway-transport +
                     tool-ledger + discovery-evidence + count checks.

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

Discovery provenance gate (signed ledger path):
  ToolLedgerValidator  — verifies tool_events.jsonl exists, signatures valid, chain intact
  DiscoveryEvidenceValidator — verifies candidate_log event present and hash matches pool
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
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
# Gateway transport validator
# ---------------------------------------------------------------------------


class GatewayTransportValidator(Validator):
    """
    Checks that the run did not use embedded transport or fall back from the gateway.

    Reads gateway_tool_activity.json if present; passes silently if absent
    (ToolLedgerValidator is the authoritative discovery evidence gate in v3).
    """

    name = "gateway_transport"

    def validate(
        self,
        manifest: AgentOutputManifest,
        spec: AgentInvocationSpec,
    ) -> AgentValidationResult:
        errors: list[ValidationError] = []
        warnings: list[ValidationWarning] = []

        summary = self._load_gateway_summary(spec)
        if summary is not None:
            errors.extend(self._validate_transport(summary))

        status = "failed" if errors else ("warning" if warnings else "passed")
        return AgentValidationResult(
            invocation_id=spec.invocation_id,
            validator_name=self.name,
            status=status,
            errors=errors,
            warnings=warnings,
        )

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


# ---------------------------------------------------------------------------
# Tool ledger validator
# ---------------------------------------------------------------------------


class ToolLedgerValidator(Validator):
    """
    Verifies that tool_events.jsonl exists, all HMAC signatures are valid,
    and the hash chain is unbroken.

    Signing key is read from TOOL_LEDGER_SIGNING_KEY env var.
    Missing key → hard fail (platform misconfiguration).
    Missing file → hard fail (all discovery must go through approved wrappers).
    """

    name = "tool_ledger"

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

        # Derive ledger path from manifest directory (platform-canonical location)
        ledger_path = Path(spec.output_manifest_path).parent / "tool_events.jsonl"

        signing_key = os.environ.get("TOOL_LEDGER_SIGNING_KEY", "")
        if not signing_key:
            errors.append(
                ValidationError(
                    field="TOOL_LEDGER_SIGNING_KEY",
                    message=(
                        "TOOL_LEDGER_SIGNING_KEY is not set — "
                        "platform configuration error; cannot verify tool ledger"
                    ),
                )
            )
            return AgentValidationResult(
                invocation_id=spec.invocation_id,
                validator_name=self.name,
                status="failed",
                errors=errors,
                warnings=warnings,
            )

        if not ledger_path.exists():
            errors.append(
                ValidationError(
                    field="tool_events.jsonl",
                    message=(
                        "tool_events.jsonl not found — "
                        "all discovery must go through approved wrappers "
                        "(career_log_candidates, career_write_manifest)"
                    ),
                )
            )
            return AgentValidationResult(
                invocation_id=spec.invocation_id,
                validator_name=self.name,
                status="failed",
                errors=errors,
                warnings=warnings,
            )

        from packages.infrastructure.tool_ledger import load_and_verify  # noqa: PLC0415

        _events, ledger_errors = load_and_verify(ledger_path, spec.invocation_id, signing_key)

        for err in ledger_errors:
            errors.append(ValidationError(field="tool_events.jsonl", message=err))

        status = "failed" if errors else ("warning" if warnings else "passed")
        return AgentValidationResult(
            invocation_id=spec.invocation_id,
            validator_name=self.name,
            status=status,
            errors=errors,
            warnings=warnings,
        )


# ---------------------------------------------------------------------------
# Discovery evidence validator
# ---------------------------------------------------------------------------


class DiscoveryEvidenceValidator(Validator):
    """
    Verifies that the signed tool ledger contains sufficient evidence for the
    claimed candidate_count.

    Only runs for DiscoveryManifest with status != "failed"
    (SchemaValidator has already caught explicitly-failed manifests).

    State A (no candidates, no signed log)  → FAIL
    State B (no candidates, signed log present) → handled by ToolLedgerValidator
    State C (candidates > 0)
      - Must have at least one candidate_log event with status="ok"
      - Last candidate_log output_hash must match sha256(candidate_pool_path)
      - Last candidate_log candidate_count must match pool line count
    """

    name = "discovery_evidence"

    def validate(
        self,
        manifest: AgentOutputManifest,
        spec: AgentInvocationSpec,
    ) -> AgentValidationResult:
        errors: list[ValidationError] = []
        warnings: list[ValidationWarning] = []

        if not isinstance(manifest, DiscoveryManifest) or manifest.status == "failed":
            return AgentValidationResult(
                invocation_id=spec.invocation_id,
                validator_name=self.name,
                status="passed",
                errors=[],
                warnings=[],
            )

        ledger_path = Path(spec.output_manifest_path).parent / "tool_events.jsonl"
        signing_key = os.environ.get("TOOL_LEDGER_SIGNING_KEY", "")

        # Load events (best-effort; ToolLedgerValidator already verified integrity)
        events: list = []
        if ledger_path.exists() and signing_key:
            try:
                from packages.infrastructure.tool_ledger import load_and_verify  # noqa: PLC0415

                events, _ = load_and_verify(ledger_path, spec.invocation_id, signing_key)
            except Exception as exc:  # noqa: BLE001
                logger.warning("DiscoveryEvidenceValidator: could not load ledger: %s", exc)

        candidate_log_events = [
            e for e in events if e.event_type == "candidate_log" and e.status == "ok"
        ]

        if manifest.candidate_count == 0:
            # 0-result runs: no signed search proof in v1 → needs_review
            errors.append(
                ValidationError(
                    field="candidate_count",
                    message=(
                        "0-result run: no signed search proof available in v1; needs_review"
                    ),
                )
            )
        else:
            # candidate_count > 0: require a valid signed candidate_log event
            if not candidate_log_events:
                errors.append(
                    ValidationError(
                        field="tool_events.jsonl",
                        message=(
                            f"candidate_count={manifest.candidate_count} but "
                            "no candidate_log event found in signed ledger — "
                            "discovery must use career_log_candidates wrapper"
                        ),
                    )
                )
            else:
                last_event = candidate_log_events[-1]
                pool_path_str = manifest.artifact_paths.get("candidate_pool")
                if pool_path_str:
                    errors.extend(
                        self._verify_pool_hash(last_event, pool_path_str, manifest.candidate_count)
                    )

        status = "failed" if errors else ("warning" if warnings else "passed")
        return AgentValidationResult(
            invocation_id=spec.invocation_id,
            validator_name=self.name,
            status=status,
            errors=errors,
            warnings=warnings,
        )

    @staticmethod
    def _verify_pool_hash(
        last_event,
        pool_path_str: str,
        reported_count: int,
    ) -> list[ValidationError]:
        errors: list[ValidationError] = []
        pool_path = Path(pool_path_str)
        if not pool_path.exists():
            return errors  # ProvenanceValidator will catch this

        actual_hash = "sha256:" + hashlib.sha256(pool_path.read_bytes()).hexdigest()
        if last_event.output_hash and last_event.output_hash != actual_hash:
            errors.append(
                ValidationError(
                    field="tool_events.jsonl",
                    message=(
                        f"candidate_pool hash mismatch — "
                        f"ledger records {last_event.output_hash!r} but "
                        f"file hashes to {actual_hash!r}"
                    ),
                )
            )

        # Count pool lines
        try:
            actual_count = sum(1 for line in pool_path.read_text().splitlines() if line.strip())
        except OSError:
            actual_count = None

        if (
            last_event.candidate_count is not None
            and actual_count is not None
            and last_event.candidate_count != actual_count
        ):
            errors.append(
                ValidationError(
                    field="tool_events.jsonl",
                    message=(
                        f"candidate_count mismatch — ledger records "
                        f"{last_event.candidate_count} but pool has {actual_count} lines"
                    ),
                )
            )

        return errors


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
            GatewayTransportValidator(),
            ToolLedgerValidator(),
            DiscoveryEvidenceValidator(),
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

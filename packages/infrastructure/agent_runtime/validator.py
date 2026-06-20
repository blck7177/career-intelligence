"""
Validator Gate v1 — schema + provenance + budget checks.

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
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path

from packages.contracts.agents.invocation import AgentInvocationSpec
from packages.contracts.agents.manifests import AgentOutputManifest, DiscoveryManifest
from packages.contracts.agents.validation import (
    AgentValidationResult,
    ValidationError,
    ValidationWarning,
)

logger = logging.getLogger(__name__)


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
            warnings.append(
                ValidationWarning(field="stop_reason", message="stop_reason is empty")
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
    For discovery manifests, also checks candidate_pool.jsonl line structure.
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

        # For discovery manifests: validate candidate_pool.jsonl line structure
        if isinstance(manifest, DiscoveryManifest):
            pool_path_str = manifest.artifact_paths.get("candidate_pool")
            if pool_path_str:
                pool_path = Path(pool_path_str)
                if pool_path.exists() and pool_path.stat().st_size > 0:
                    parse_errors = self._check_candidate_pool(pool_path)
                    errors.extend(parse_errors)

        status = "failed" if errors else ("warning" if warnings else "passed")
        return AgentValidationResult(
            invocation_id=spec.invocation_id,
            validator_name=self.name,
            status=status,
            errors=errors,
            warnings=warnings,
        )

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
        ]

    def run(
        self,
        manifest: AgentOutputManifest,
        spec: AgentInvocationSpec,
    ) -> list[AgentValidationResult]:
        results: list[AgentValidationResult] = []
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

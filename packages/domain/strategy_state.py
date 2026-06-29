"""
Strategy state reducer — validate, merge, and materialize discovery hints.

Pure domain logic: no DB, no IO except reading taxonomy/schema from disk.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import jsonschema
from jsonschema import Draft7Validator

from packages.contracts.agents.discovery_intent import (
    PreviousRunDiagnostics,
    SourceRegistrySnapshot,
)
from packages.contracts.strategy.state import (
    SearchStrategyState,
    StrategyPatch,
    StrategyPatchError,
)
from packages.domain.reports.taxonomy import get_taxonomy

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2] / "tools" / "schemas" / "strategy_patch.schema.json"
)

_ATS_BOARD_HINTS = (
    "greenhouse.io",
    "boards.greenhouse.io",
    "lever.co",
    "jobs.lever.co",
    "ashbyhq.com",
    "jobs.ashbyhq.com",
    "myworkdayjobs.com",
    "workday.com",
    "icims.com",
    "smartrecruiters.com",
    "taleo.net",
    "eightfold.ai",
    "jobs/",
    "careers/",
    "careers.",
)


def _load_schema_validator() -> Draft7Validator:
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    return Draft7Validator(schema)


def _build_taxonomy_maps() -> tuple[dict[str, str], dict[str, str]]:
    """Return (id_to_label, label_to_id) maps from role category taxonomy."""
    id_to_label: dict[str, str] = {}
    label_to_id: dict[str, str] = {}
    for entry in get_taxonomy():
        cat_id = entry.get("id")
        label = entry.get("label")
        if cat_id and label:
            id_to_label[str(cat_id)] = str(label)
            label_to_id[str(label)] = str(cat_id)
    return id_to_label, label_to_id


def _normalize_coverage_keys(
    coverage: dict[str, str],
    *,
    id_to_label: dict[str, str],
    label_to_id: dict[str, str],
) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key, value in coverage.items():
        if key in id_to_label:
            normalized[key] = value
        elif key in label_to_id:
            normalized[label_to_id[key]] = value
        else:
            raise StrategyPatchError(
                f"coverage_by_role_category key {key!r} is not a valid role category id or label"
            )
    return normalized


def _merge_lists(existing: list[str], incoming: list[str]) -> list[str]:
    seen: set[str] = set()
    merged: list[str] = []
    for item in existing + incoming:
        item = item.strip()
        if not item or item in seen:
            continue
        seen.add(item)
        merged.append(item)
    return merged


def is_board_source(source: str) -> bool:
    """Heuristic: ATS board or career-site URL suitable for known_boards."""
    lower = source.lower().strip()
    if not lower:
        return False
    return any(hint in lower for hint in _ATS_BOARD_HINTS)


_ALLOWED_PATCH_FIELDS = frozenset(
    {
        "effective_sources",
        "avoid_sources",
        "effective_query_patterns",
        "avoid_query_patterns",
        "coverage_by_role_category",
        "key_learnings",
        "recommended_next_searches",
    }
)

_LIST_PATCH_FIELDS = _ALLOWED_PATCH_FIELDS - {
    "coverage_by_role_category",
    "recommended_next_searches",
}

_ENVELOPE_KEYS = frozenset(
    {
        "run_id",
        "invocation_id",
        "metadata",
        "summary",
        "patches_proposed",
    }
)

_SUPPORTED_PATCH_ACTIONS = frozenset({"add", "set", "replace", "update"})


def _merge_patch_list_field(flat: dict[str, Any], field: str, value: Any) -> None:
    items = value if isinstance(value, list) else [value]
    existing = flat.get(field, [])
    if not isinstance(existing, list):
        raise StrategyPatchError(f"patch field {field!r} must be a list")
    flat[field] = [*existing, *[str(item) for item in items]]


def _apply_patch_operation(flat: dict[str, Any], op: dict[str, Any], index: int) -> None:
    field = op.get("field")
    if not field or field not in _ALLOWED_PATCH_FIELDS:
        raise StrategyPatchError(f"patches[{index}] has unknown field {field!r}")

    action = str(op.get("action", "add")).lower()
    if action not in _SUPPORTED_PATCH_ACTIONS:
        raise StrategyPatchError(
            f"patches[{index}] has unsupported action {action!r} for field {field!r}"
        )

    value = op.get("value")
    if field == "coverage_by_role_category":
        if not isinstance(value, dict):
            raise StrategyPatchError(
                f"patches[{index}] value for coverage_by_role_category must be an object"
            )
        merged = dict(flat.get(field, {}))
        merged.update(value)
        flat[field] = merged
        return

    if field == "recommended_next_searches":
        if not isinstance(value, list):
            raise StrategyPatchError(
                f"patches[{index}] value for recommended_next_searches must be an array"
            )
        flat[field] = [str(item) for item in value]
        return

    if field in _LIST_PATCH_FIELDS:
        _merge_patch_list_field(flat, field, value)
        return

    raise StrategyPatchError(f"patches[{index}] has unknown field {field!r}")


def normalize_strategy_patch_raw(raw: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """
    Convert agent-friendly nested patch envelopes into the flat StrategyPatch object.

    Handles:
    - {"patches": [{"field": "...", "action": "add", "value": ...}]}
    - {"run_id": "...", "effective_sources": [...]} (strips envelope keys)

    Returns (normalized_dict, was_normalized).
    """
    if not isinstance(raw, dict):
        raise StrategyPatchError("strategy patch must be a JSON object")

    if "patches" in raw:
        patches = raw["patches"]
        if not isinstance(patches, list):
            raise StrategyPatchError("patches must be an array")
        flat: dict[str, Any] = {}
        for index, op in enumerate(patches):
            if not isinstance(op, dict):
                raise StrategyPatchError(f"patches[{index}] must be an object")
            _apply_patch_operation(flat, op, index)
        return flat, True

    extra_keys = set(raw.keys()) - _ALLOWED_PATCH_FIELDS
    if extra_keys and extra_keys <= _ENVELOPE_KEYS:
        stripped = {key: raw[key] for key in raw if key in _ALLOWED_PATCH_FIELDS}
        return stripped, True

    return raw, False


def validate_strategy_patch(raw: dict[str, Any]) -> StrategyPatch:
    """
    Validate raw patch dict against strategy_patch.schema.json and taxonomy keys.
    Raises StrategyPatchError on failure.
    """
    if not isinstance(raw, dict):
        raise StrategyPatchError("strategy patch must be a JSON object")

    normalized_raw, _ = normalize_strategy_patch_raw(raw)

    validator = _load_schema_validator()
    errors = sorted(validator.iter_errors(normalized_raw), key=lambda e: e.path)
    if errors:
        messages = "; ".join(e.message for e in errors[:5])
        raise StrategyPatchError(f"strategy patch schema validation failed: {messages}")

    id_to_label, label_to_id = _build_taxonomy_maps()
    normalized = dict(normalized_raw)
    if "coverage_by_role_category" in normalized_raw and normalized_raw["coverage_by_role_category"]:
        normalized["coverage_by_role_category"] = _normalize_coverage_keys(
            normalized_raw["coverage_by_role_category"],
            id_to_label=id_to_label,
            label_to_id=label_to_id,
        )

    return StrategyPatch.model_validate(normalized)


def apply_strategy_patch(
    state: SearchStrategyState | None,
    patch: StrategyPatch,
    *,
    workspace_id: str,
    reflection_run_id: str,
    reflection_task_id: str,
    profile_id: str | None = None,
) -> SearchStrategyState:
    """Deterministically merge patch into strategy state."""
    base = state or SearchStrategyState.empty(workspace_id, profile_id=profile_id)
    now = datetime.now(timezone.utc)

    merged_coverage = dict(base.coverage_by_role_category)
    merged_coverage.update(patch.coverage_by_role_category)

    recommended = (
        patch.recommended_next_searches
        if patch.recommended_next_searches
        else base.recommended_next_searches
    )

    return SearchStrategyState(
        workspace_id=workspace_id,
        profile_id=profile_id or base.profile_id,
        effective_sources=_merge_lists(base.effective_sources, patch.effective_sources),
        avoid_sources=_merge_lists(base.avoid_sources, patch.avoid_sources),
        effective_query_patterns=_merge_lists(
            base.effective_query_patterns, patch.effective_query_patterns
        ),
        avoid_query_patterns=_merge_lists(
            base.avoid_query_patterns, patch.avoid_query_patterns
        ),
        coverage_by_role_category=merged_coverage,
        key_learnings=_merge_lists(base.key_learnings, patch.key_learnings),
        recommended_next_searches=recommended,
        last_reflection_run_id=reflection_run_id,
        last_reflection_task_id=reflection_task_id,
        updated_at=now,
    )


def materialize_discovery_hints(
    state: SearchStrategyState,
) -> tuple[SourceRegistrySnapshot, PreviousRunDiagnostics]:
    """Map canonical strategy state into DiscoveryTaskSpec hint fields.

    Combines heuristic board detection from effective_sources with
    structurally registered boards from company_sources table.
    """
    id_to_label, _ = _build_taxonomy_maps()

    known_boards = [s for s in state.effective_sources if is_board_source(s)]

    # Supplement with all non-blocked boards from company_sources DB table.
    try:
        from packages.infrastructure.db.session import get_session
        from packages.infrastructure.db.repositories import CompanySourceRepository

        with get_session() as session:
            for src in CompanySourceRepository(session).list_known():
                if src.board_careers_url and src.board_careers_url not in known_boards:
                    known_boards.append(src.board_careers_url)
    except Exception:
        pass

    extra_learnings = list(state.key_learnings)
    for pattern in state.avoid_query_patterns:
        extra_learnings.append(f"Avoid query pattern: {pattern}")

    coverage_gaps: list[str] = []
    for cat_id, level in state.coverage_by_role_category.items():
        if level in ("weak", "missing"):
            label = id_to_label.get(cat_id, cat_id)
            coverage_gaps.append(f"{label} ({level})")

    avoid_with_hint = [
        f"{s} (may be temporary — retry if no alternatives)"
        if "block" in s.lower() or "403" in s
        else s
        for s in state.avoid_sources
    ]

    source_snapshot = SourceRegistrySnapshot(
        known_boards=known_boards,
        avoid_sources=avoid_with_hint,
        effective_query_patterns=list(state.effective_query_patterns),
    )
    previous_diagnostics = PreviousRunDiagnostics(
        coverage_gaps=coverage_gaps,
        key_learnings=extra_learnings,
        recommended_next_searches=list(state.recommended_next_searches),
    )
    return source_snapshot, previous_diagnostics


def state_from_db_row(
    *,
    workspace_id: str,
    profile_id: str | None,
    state_json: dict[str, Any],
    last_reflection_run_id: str | None,
    last_reflection_task_id: str | None,
    updated_at: datetime,
) -> SearchStrategyState:
    """Reconstruct SearchStrategyState from a DB row."""
    data = dict(state_json or {})
    return SearchStrategyState(
        workspace_id=workspace_id,
        profile_id=profile_id,
        effective_sources=data.get("effective_sources") or [],
        avoid_sources=data.get("avoid_sources") or [],
        effective_query_patterns=data.get("effective_query_patterns") or [],
        avoid_query_patterns=data.get("avoid_query_patterns") or [],
        coverage_by_role_category=data.get("coverage_by_role_category") or {},
        key_learnings=data.get("key_learnings") or [],
        recommended_next_searches=data.get("recommended_next_searches") or [],
        last_reflection_run_id=last_reflection_run_id,
        last_reflection_task_id=last_reflection_task_id,
        updated_at=updated_at,
    )


def state_to_db_json(state: SearchStrategyState) -> dict[str, Any]:
    """Serialize mergeable state fields for state_json column."""
    return {
        "effective_sources": state.effective_sources,
        "avoid_sources": state.avoid_sources,
        "effective_query_patterns": state.effective_query_patterns,
        "avoid_query_patterns": state.avoid_query_patterns,
        "coverage_by_role_category": state.coverage_by_role_category,
        "key_learnings": state.key_learnings,
        "recommended_next_searches": state.recommended_next_searches,
    }

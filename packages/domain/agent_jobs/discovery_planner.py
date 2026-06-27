"""
Discovery planner — builds DiscoveryTaskSpec from DiscoveryIntent + context.

Pure domain logic: no IO, no LLM, no DB, no infrastructure imports.
Called by the worker after intent translation, before writing input.json.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from packages.contracts.agents.discovery_intent import (
    CatalogContext,
    DiscoveryIntent,
    DiscoveryTaskSpec,
    OutputPaths,
    PreviousRunDiagnostics,
    SourceRegistrySnapshot,
)
from packages.contracts.agents.invocation import AgentBudget


# ---------------------------------------------------------------------------
# Budget policy
# ---------------------------------------------------------------------------

BUDGET_BY_DEPTH: dict[str, AgentBudget] = {
    "quick": AgentBudget(
        max_tool_calls=15,
        max_candidates=20,
        max_new_sources=5,
        timeout_seconds=600,
    ),
    "standard": AgentBudget(
        max_tool_calls=30,
        max_candidates=50,
        max_new_sources=10,
        timeout_seconds=900,
    ),
    "deep": AgentBudget(
        max_tool_calls=60,
        max_candidates=100,
        max_new_sources=20,
        timeout_seconds=1800,
    ),
}

_DEFAULT_DEPTH: Literal["standard"] = "standard"


def budget_for_depth(search_depth: str) -> AgentBudget:
    """
    Return the AgentBudget for a given search_depth string.
    Falls back to "standard" for unknown values.
    """
    return BUDGET_BY_DEPTH.get(search_depth, BUDGET_BY_DEPTH[_DEFAULT_DEPTH])


# ---------------------------------------------------------------------------
# Output path builder
# ---------------------------------------------------------------------------


def build_output_paths(
    artifacts_dir: str,
    run_id: str,
    task_id: str,
) -> OutputPaths:
    """
    Build the output file paths for a discovery run.
    All paths are under <artifacts_dir>/<run_id>/<task_id>/.
    """
    base = Path(artifacts_dir) / run_id / task_id
    return OutputPaths(
        candidate_pool_path=str(base / "candidate_pool.jsonl"),
        search_ledger_path=str(base / "search_ledger.jsonl"),
        trace_events_path=str(base / "trace_events.jsonl"),
        coverage_report_path=str(base / "coverage_report.md"),
        output_manifest_path=str(base / "output_manifest.json"),
        tool_events_path=str(base / "tool_events.jsonl"),
    )


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------


def build_discovery_task_spec(
    *,
    discovery_intent: DiscoveryIntent,
    search_depth: str,
    artifacts_dir: str,
    run_id: str,
    task_id: str,
    catalog_context: CatalogContext | None = None,
    source_registry_snapshot: SourceRegistrySnapshot | None = None,
    previous_run_diagnostics: PreviousRunDiagnostics | None = None,
) -> DiscoveryTaskSpec:
    """
    Assemble the DiscoveryTaskSpec that gets written to input.json.

    This is a pure function:
      - discovery_intent comes from IntentTranslator
      - budget is derived from search_depth (deterministic)
      - output_paths are derived from run_id + task_id
      - platform context (catalog, sources, history) is passed in from the worker

    The worker is responsible for querying DB / configs to populate
    catalog_context, source_registry_snapshot, and previous_run_diagnostics
    before calling this function. For MVP all three default to None.
    """
    budget = budget_for_depth(search_depth)
    output_paths = build_output_paths(artifacts_dir, run_id, task_id)

    return DiscoveryTaskSpec(
        discovery_intent=discovery_intent,
        catalog_context=catalog_context,
        source_registry_snapshot=source_registry_snapshot,
        previous_run_diagnostics=previous_run_diagnostics,
        budget=budget,
        output_paths=output_paths,
    )

"""
Agent output manifest contracts.

The agent writes AgentOutputManifest to output_manifest_path.
The worker validator reads it to decide what to persist.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class AgentOutputManifest(BaseModel):
    """
    Written by the agent to output_manifest_path before stopping.
    Validated by the Validator Gate before any DB write.
    """

    invocation_id: str
    status: Literal["completed", "partial", "failed"]
    stop_reason: str

    # Paths to output files (all on agent_artifacts volume)
    artifact_paths: dict[str, str] = Field(
        default_factory=dict,
        description="artifact_type → absolute path on volume",
    )

    # Summary stats (validated by gate)
    summary: dict = Field(default_factory=dict)


class DiscoveryManifest(AgentOutputManifest):
    """Output manifest for agent.job_discovery tasks."""

    candidate_count: int = 0
    sources_tried: list[str] = Field(default_factory=list)
    sources_added: list[str] = Field(default_factory=list)

    # artifact_paths keys expected:
    #   "candidate_pool"  → candidate_pool.jsonl
    #   "search_ledger"   → search_ledger.jsonl
    #   "trace_events"    → trace_events.jsonl


class ResearchManifest(AgentOutputManifest):
    """Output manifest for agent.job_research tasks."""

    job_id: str
    citations_count: int = 0
    jd_text: Optional[str] = None

    # artifact_paths keys expected:
    #   "research_notes"  → research_notes.md
    #   "sources"         → research_sources.json


class ReflectionManifest(AgentOutputManifest):
    """Output manifest for agent.run_reflection tasks."""

    run_id: str
    patches_proposed: int = 0

    # artifact_paths keys expected:
    #   "reflection_report" → reflection_report.md
    #   "strategy_patch"    → strategy_patch.json

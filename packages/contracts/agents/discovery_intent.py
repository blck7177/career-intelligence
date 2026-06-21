"""
Agent-facing discovery schemas.

These are the structured objects that flow through the intent translation
pipeline and into input.json on the agent_artifacts volume.

Hierarchy:
  JobDiscoveryFrontendInput  (user input, contracts/api/discovery.py)
    ↓ IntentTranslator
  DiscoveryIntent            (structured intent, what to find)
    ↓ build_discovery_task_spec()
  DiscoveryTaskSpec          (agent input = intent + platform context + execution contract)
    → written to input.json payload
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from packages.contracts.agents.invocation import AgentBudget
from packages.contracts.api.discovery import DiscoveryHardConstraints


# ---------------------------------------------------------------------------
# ProfileSnapshot
# ---------------------------------------------------------------------------


class ProfileSnapshot(BaseModel):
    """
    Point-in-time snapshot of a workspace member's career profile.

    All fields are optional. An empty profile is valid — agents should
    treat it as "no profile context available" and proceed on intent alone.

    MVP: profiles are not yet persisted in DB. ProfileSnapshot.empty()
    is always used until workspace_profiles table exists.
    """

    profile_id: Optional[str] = None
    summary: Optional[str] = None
    # e.g. "Risk analytics professional with 4 years in model validation and market risk"

    experience_summary: Optional[str] = None
    # Brief narrative of work history relevant to discovery

    technical_skills: list[str] = Field(default_factory=list)
    # e.g. ["Python", "R", "VaR", "stress testing", "scenario analysis"]

    domain_areas: list[str] = Field(default_factory=list)
    # e.g. ["market risk", "model risk", "credit risk", "PPNR"]

    years_of_experience: Optional[int] = None

    education_summary: Optional[str] = None
    # e.g. "MS Financial Engineering, Columbia University"

    @classmethod
    def empty(cls) -> "ProfileSnapshot":
        """Return an empty profile. Used when no profile_id is provided."""
        return cls()

    @property
    def is_empty(self) -> bool:
        """True if no meaningful profile data is present."""
        return not any(
            [
                self.summary,
                self.experience_summary,
                self.technical_skills,
                self.domain_areas,
            ]
        )


# ---------------------------------------------------------------------------
# RoleFamily
# ---------------------------------------------------------------------------


class RoleFamily(BaseModel):
    """
    A role direction included in or excluded from the discovery.

    The source field is critical for auditability and guardrails:
      user_explicit    = user mentioned this directly in their request
      profile_signal   = derived from profile capabilities, not user's words
      inferred_adjacent = semantically close to something user mentioned;
                          only allowed when the adjacency is obvious and
                          not creative speculation
    """

    name: str
    # e.g. "market risk analytics", "valuation control", "exposure management"

    rationale: str
    # Non-empty. Why this family is included or excluded.
    # e.g. "User explicitly mentioned 'valuation control'"
    # e.g. "IPV is the standard abbreviation for Independent Price Verification,
    #        a direct synonym for valuation control"

    source: Literal["user_explicit", "profile_signal", "inferred_adjacent"]

    confidence: Literal["high", "medium", "low"] = "high"
    # high   = clear, unambiguous mapping
    # medium = plausible but the user's wording was ambiguous
    # low    = speculative; will appear in ambiguity_flags


# ---------------------------------------------------------------------------
# CapabilitySignal
# ---------------------------------------------------------------------------


class CapabilitySignal(BaseModel):
    """
    A capability cluster extracted from the user's profile.

    Only populated when profile_role is "supporting" or "primary".
    Never used to generate hard constraints — only soft signals.
    """

    cluster_name: str
    # e.g. "VaR / stress testing", "PPNR modeling", "Python analytics workflow"

    description: str
    # Short description of what this cluster represents and why it matters

    adjacent_role_targets: list[str]
    # Role families this capability plausibly maps to
    # e.g. ["exposure management", "portfolio risk analytics"]

    signal_type: Literal["domain", "technical", "business"]
    # domain   = financial domain knowledge (e.g. VaR, credit risk)
    # technical = tools, methods, quantitative skills
    # business = process, governance, stakeholder, communication skills


# ---------------------------------------------------------------------------
# DiscoveryIntent
# ---------------------------------------------------------------------------


class DiscoveryIntent(BaseModel):
    """
    Output of the IntentTranslator.

    Answers: What does the user want to find?
    Does NOT answer: How to search? Which sources? What queries?

    Built from: user's frontend input + optional profile.
    Does NOT contain: source strategy, query plans, budget allocation.

    This is the stable, auditable record of user intent. It is stored in
    task_events (event_type="intent_translated") and is visible in the UI.
    """

    # --- Traceability ---
    translator_version: str = "v1.0"
    raw_user_request: str
    # Preserved verbatim from frontend input for audit trail

    # --- Core intent ---
    interpreted_goal: str
    # One sentence. What the agent is trying to achieve.
    # e.g. "Find NYC market-facing analytics roles adjacent to market risk,
    #       excluding pure model validation, at associate/AVP level."

    search_mode: Literal["direct", "exploratory", "profile_guided"]

    # --- Role targets ---
    target_role_families: list[RoleFamily]
    # Non-empty for a non-blocking result. Each has source + rationale.

    excluded_role_families: list[RoleFamily]
    # May be empty. source MUST be "user_explicit" for all exclusions.
    # Platform never auto-adds exclusions based on profile or inference.

    # --- Constraints ---
    hard_constraints: DiscoveryHardConstraints
    # Identical to frontend input — not enriched by the translator.

    soft_preferences: list[str] = Field(default_factory=list)
    # e.g. ["prefer H1B-transfer friendly", "prefer buy-side over sell-side"]
    # Must come from the user's words, not profile inference.

    # --- Profile context ---
    profile_role: Literal["none", "supporting", "primary"]
    # Derived from search_mode (deterministic, not LLM-decided):
    #   direct         → "none" (or "supporting" if profile provided)
    #   exploratory    → "supporting"
    #   profile_guided → "primary"

    capability_signals: list[CapabilitySignal] = Field(default_factory=list)
    # Empty if profile_role = "none" or no profile provided.

    # --- Agent guidance ---
    expansion_scope: Literal["narrow", "standard", "wide"]
    # Derived deterministically from search_mode (NOT by the LLM):
    #   direct         → "narrow"  (synonyms + title aliases only, no expansion)
    #   exploratory    → "standard"
    #   profile_guided → "standard"

    ambiguity_flags: list[str] = Field(default_factory=list)
    # Preserved uncertainties. Not resolved by the translator.
    # e.g. ["'risk analytics' could include credit or market risk — not resolved"]
    # Used for UI preview and post-run diagnostics.
    # Blocking ambiguity: target_role_families is empty → task goes to needs_review.
    # Non-blocking ambiguity: flags present but target_role_families non-empty → warning.


# ---------------------------------------------------------------------------
# DiscoveryTaskSpec (what agent reads from input.json)
# ---------------------------------------------------------------------------


class CatalogContext(BaseModel):
    """Snapshot of existing discovered jobs for deduplication."""

    existing_job_count: int = 0
    recently_seen_companies: list[str] = Field(default_factory=list)
    # Company names already in catalog — agent avoids re-discovering these
    recently_seen_urls: list[str] = Field(default_factory=list)
    # Job URLs already seen — hard dedup, agent must not re-log these


class SourceRegistrySnapshot(BaseModel):
    """Known ATS boards and their reliability status."""

    known_boards: list[str] = Field(default_factory=list)
    # ATS URLs known to be active for this workspace
    avoid_sources: list[str] = Field(default_factory=list)
    # Sources known to fail (bot-blocked, login-required, etc.)
    effective_query_patterns: list[str] = Field(default_factory=list)
    # Query patterns that have produced real results historically


class PreviousRunDiagnostics(BaseModel):
    """Summary of previous run outcomes to guide this run."""

    coverage_gaps: list[str] = Field(default_factory=list)
    # e.g. ["buy-side risk", "Ashby-board companies"]
    key_learnings: list[str] = Field(default_factory=list)
    # e.g. ["JPMorgan board_sync filter too narrow; broaden title_keywords"]
    recommended_next_searches: list[str] = Field(default_factory=list)
    # e.g. ["Retry exposure management with broader title scope"]


class OutputPaths(BaseModel):
    """Paths on the agent_artifacts volume that the agent must write."""

    candidate_pool_path: str
    search_ledger_path: str
    trace_events_path: str
    coverage_report_path: str
    output_manifest_path: str


class DiscoveryTaskSpec(BaseModel):
    """
    The complete input written to input.json for the career-search-agent.

    = DiscoveryIntent (what to find)
    + platform context (catalog, sources, history)
    + execution contract (budget, output paths)

    The agent reads this and decides HOW to search.
    The platform decides WHAT to search for (via DiscoveryIntent).
    """

    discovery_intent: DiscoveryIntent

    catalog_context: Optional[CatalogContext] = None
    source_registry_snapshot: Optional[SourceRegistrySnapshot] = None
    previous_run_diagnostics: Optional[PreviousRunDiagnostics] = None

    budget: AgentBudget
    output_paths: OutputPaths

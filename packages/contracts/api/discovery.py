"""
API DTOs for job_discovery runs.

JobDiscoveryFrontendInput is placed into input_snapshot when
run_type = "job_discovery".

Rules:
  - Every field here comes directly from the user.
  - Nothing is inferred, defaulted, or enriched by the platform at this layer.
  - Platform context (profile, catalog, strategy) is injected later by the worker.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class DiscoveryHardConstraints(BaseModel):
    """
    Explicit constraints the user provided.

    All fields are optional. An absent field means the user did not specify
    that constraint — the platform must NOT infer a default value for it.
    """

    location: Optional[str] = None
    # e.g. "NYC", "New York / New Jersey", "remote US"
    # None = user did not specify a location constraint

    seniority: list[str] = Field(default_factory=list)
    # e.g. ["analyst", "associate", "avp"]
    # Empty = no seniority constraint

    exclude_role_types: list[str] = Field(default_factory=list)
    # e.g. ["model_validation", "pure_audit", "treasury_reporting"]

    must_include_keywords: list[str] = Field(default_factory=list)
    # e.g. ["market risk"]
    # Must come from the user's explicit words, never inferred from profile

    work_arrangement: Optional[Literal["hybrid", "remote", "onsite", "any"]] = None
    # None = user did not specify

    visa_note: Optional[str] = None
    # Free text, e.g. "H1B transfer only", "no sponsorship needed"
    # Not structured intentionally — preserved verbatim for agent

    compensation_range: Optional[str] = None
    # Free text, e.g. "$120k–$160k", "above $150k base"
    # Absent means unknown — agents must NOT auto-reject on this basis


class JobDiscoveryFrontendInput(BaseModel):
    """
    The structured frontend payload for a job_discovery run.

    Placed into RunCreate.input_snapshot by the frontend.
    The worker parses this before calling the IntentTranslator.

    Profile, catalog context, and strategy context are NOT here —
    they are injected by the worker/planner from platform state.
    """

    raw_user_request: str = Field(
        ...,
        min_length=5,
        description="User's natural language description of what they are looking for.",
    )

    search_mode: Literal["direct", "exploratory", "profile_guided"]
    # direct         = user knows exactly what role they want; minimal expansion
    # exploratory    = user knows a direction; system may expand to adjacent roles
    # profile_guided = profile capabilities drive lane generation

    hard_constraints: DiscoveryHardConstraints = Field(
        default_factory=DiscoveryHardConstraints
    )

    profile_id: Optional[str] = None
    # Optional reference to a workspace profile.
    # Required for search_mode = "profile_guided".
    # MVP: if None, ProfileSnapshot.empty() is used.

    search_depth: Literal["quick", "standard", "deep"] = "standard"
    # quick    → ~15 tool calls, ~20 candidates max
    # standard → ~30 tool calls, ~50 candidates max
    # deep     → ~60 tool calls, ~100 candidates max

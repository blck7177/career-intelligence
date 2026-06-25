"""
CandidateProfile — unified candidate profile contract.

Single source of truth for both Discovery and FitReport pipelines.

Discovery uses a subset of fields (narrative + subject_areas/skills) via ProfileSnapshot
adapter in packages/contracts/agents/discovery_intent.py.

FitReport reads all fields directly from this model, loaded from candidate_profiles table
by the worker. Frontend no longer submits profile data on fit_report runs.

Fields removed vs old split models:
  - analytical_methods: merged into technical_skills (UI label: "Technical skills / methods")
  - current_background: merged into summary
  - domain_experience + finance_domains: merged into subject_areas

Fields unified vs old split models:
  - years_of_experience (Discovery) / years_experience (FitReport) → years_experience
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class RepresentativeProject(BaseModel):
    title: str = ""
    description: str = ""
    skills_used: list[str] = Field(default_factory=list)
    quantified_impact: str = ""


class CandidateProfile(BaseModel):
    """
    Unified candidate profile for Discovery and FitReport.

    All list fields default to empty list so downstream LLM prompts never
    see a TypeError from join() on None.
    """

    # Identity (set by DB / API layer, not by user input)
    id: Optional[str] = None
    workspace_id: Optional[str] = None
    profile_hash: Optional[str] = None

    # Narrative — Discovery LLM reads summary + experience_summary + education_summary
    # FitReport LLM reads summary as the "Background" context line
    summary: str = ""
    experience_summary: str = ""
    education_summary: str = ""

    # Quantitative (unified naming)
    years_experience: Optional[int] = None

    # Skills & subject areas
    # technical_skills also covers analytical methods (UI: "Technical skills / methods")
    technical_skills: list[str] = Field(default_factory=list)
    subject_areas: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)

    # Projects — primary evidence for FitReport strong_matches / gaps
    representative_projects: list[RepresentativeProject] = Field(default_factory=list)

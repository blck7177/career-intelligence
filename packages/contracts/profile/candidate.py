"""
CandidateProfile — Pydantic contract for candidate profile data passed to fit report generation.

Finance-focused schema: designed for investment banking, asset management,
and financial institution roles.

Used in:
  - fit_report_service.create_fit_report() — validates incoming profile_snapshot
  - FitReportForm (web) — UI fields mirror these names
  - fit_reporter._build_user_prompt() — reads these exact field names
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
    Candidate profile for fit report generation.

    All list fields default to empty list so the LLM prompt never sees
    a TypeError from join() on a None value.
    """

    id: Optional[str] = None
    years_experience: Optional[int] = None
    current_background: str = ""
    domain_experience: list[str] = Field(default_factory=list)
    technical_skills: list[str] = Field(default_factory=list)
    analytical_methods: list[str] = Field(default_factory=list)
    finance_domains: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    representative_projects: list[RepresentativeProject] = Field(default_factory=list)

"""
Pydantic contracts for Candidate Fit Reports.

These models mirror the JSON output from fit_reporter.py.
FIT_SCORE range: 0-100 (80+ strong, 60-79 good with gaps, <60 significant gaps).
"""
from __future__ import annotations
from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field


class StrongMatch(BaseModel):
    demand: str
    evidence: str


class PartialMatch(BaseModel):
    demand: str
    gap_description: str


class FitGap(BaseModel):
    demand: str
    gap_description: str
    severity: Literal["blocking", "significant", "minor"] = "minor"


class ResumeRewriteStrategy(BaseModel):
    """
    MVP: kept as resume_rewrite_strategy for LLM/schema compatibility.
    Use .application_positioning property in UI/API layer.
    """
    positioning: str = ""
    keywords_to_add: list[str] = Field(default_factory=list)
    bullets_to_reframe: list[str] = Field(default_factory=list)
    evidence_to_surface: list[str] = Field(default_factory=list)

    @property
    def application_positioning(self) -> str:
        return self.positioning


class FitReportStructured(BaseModel):
    """
    Structured output from fit_reporter.
    Used as complete_structured() response_schema.
    overall_match_score: 0-100 integer.
    """
    fit_report_id: str = ""
    workspace_id: str = ""
    job_id: str = ""
    job_report_id: str = ""
    candidate_profile_id: str = ""
    analyzed_at: str = ""
    prompt_version: str = ""

    overall_match_score: int = Field(default=0, ge=0, le=100)
    match_summary: str = ""

    strong_matches: list[StrongMatch] = Field(default_factory=list)
    partial_matches: list[PartialMatch] = Field(default_factory=list)
    gaps: list[FitGap] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    interview_talking_points: list[str] = Field(default_factory=list)
    resume_rewrite_strategy: ResumeRewriteStrategy = Field(default_factory=ResumeRewriteStrategy)
    recommended_next_action: str = ""

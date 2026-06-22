"""
Pydantic contracts for Job Intelligence Reports.

These models mirror the Layer 2 structured output from role_analyzer.py.
They are used as:
  - complete_structured() response_schema in LLM calls
  - DB structured_json serialization
  - API read DTOs
"""
from __future__ import annotations
from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field


class BusinessContext(BaseModel):
    summary: str = ""
    problem_solved: str = ""
    evidence: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "low"


class PositionFunction(BaseModel):
    primary_function: str = "unknown"
    secondary_functions: list[str] = Field(default_factory=list)
    function_mix_description: str = ""
    reason: str = ""
    evidence: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "low"


class DailyWorkflow(BaseModel):
    likely_inputs: list[str] = Field(default_factory=list)
    likely_analyses: list[str] = Field(default_factory=list)
    likely_outputs: list[str] = Field(default_factory=list)
    likely_stakeholders: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)


class UnderlyingSkillDemand(BaseModel):
    jd_phrase: str = ""
    demand_type: Literal[
        "domain_knowledge",
        "technical_skill",
        "analytical_capability",
        "workflow_capability",
        "stakeholder_capability",
        "business_context_knowledge",
        "operating_judgment",
        "mixed",
    ] = "mixed"
    underlying_capability: str = ""
    importance: Literal["core", "supporting", "nice_to_have"] = "supporting"
    research_contribution: str = ""
    evidence: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "medium"


class UncertaintyNote(BaseModel):
    issue: str = ""
    impact: str = ""


class JobReportStructured(BaseModel):
    """
    Structured output from Layer 2 of role_analyzer.
    Used as complete_structured() response_schema.
    """
    business_context: BusinessContext = Field(default_factory=BusinessContext)
    position_function: PositionFunction = Field(default_factory=PositionFunction)
    daily_workflow: DailyWorkflow = Field(default_factory=DailyWorkflow)
    underlying_skill_demands: list[UnderlyingSkillDemand] = Field(default_factory=list)
    primary_workstream: str = "unknown"
    secondary_workstreams: list[str] = Field(default_factory=list)
    workstream_evidence: list[str] = Field(default_factory=list)
    workstream_confidence: Literal["high", "medium", "low"] = "low"
    uncertainty_notes: list[UncertaintyNote] = Field(default_factory=list)
    analyst_notes: str = ""

    # Research provenance — stamped by service layer, not LLM
    used_research: bool = False
    research_bundle_hash: str = "none"
    research_validation_status: Optional[Literal["passed", "partial", "failed"]] = None
    research_source_count: int = 0

"""
Contracts for the Resume Tailor pipeline.

The pipeline takes a candidate's structured resume + a target job's analysis
and produces a strategically tailored resume where each bullet is designed
as evidence for the role's capability requirements.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Step 2: Workstream analysis (岗位侧)
# ---------------------------------------------------------------------------


class EvidenceRequirement(BaseModel):
    """What the resume must prove for a specific capability."""
    capability: str
    importance: Literal["core", "supporting", "nice_to_have"] = "supporting"
    what_evidence_looks_like: list[str] = Field(default_factory=list)


class WorkstreamAnalysis(BaseModel):
    workstreams: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    evidence_requirements: list[EvidenceRequirement] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Step 3: Fact atoms (候选人侧)
# ---------------------------------------------------------------------------


class FactAtom(BaseModel):
    experience_index: int
    bullet_index: int
    context: str = ""
    action: str = ""
    method: str = ""
    output: str = ""
    stakeholder: str = ""
    impact: str = ""


class ExperienceWorkflow(BaseModel):
    experience_index: int
    workflow_description: str = ""
    capabilities_demonstrated: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Step 4: Evidence matching
# ---------------------------------------------------------------------------


class EvidenceMatch(BaseModel):
    capability: str
    strength: Literal["direct", "adjacent", "supporting", "weak", "gap"]
    source_experience_index: Optional[int] = None
    source_bullet_index: Optional[int] = None
    evidence_summary: str = ""


# ---------------------------------------------------------------------------
# Step 5-6: Section plans + bullet edits
# ---------------------------------------------------------------------------


class SectionPlan(BaseModel):
    experience_index: int
    employer: str = ""
    title: str = ""
    story_arc: str = ""
    bullet_claims: list[str] = Field(default_factory=list)


class BulletEdit(BaseModel):
    experience_index: int
    bullet_index: int
    original: str
    operation: Literal["keep", "light_edit", "reframe", "compress", "replace"]
    claim: str
    revised: str
    evidence_strength: Literal["direct", "adjacent", "supporting"]
    rationale: str


# ---------------------------------------------------------------------------
# Step 7: Audit
# ---------------------------------------------------------------------------


class AuditIssue(BaseModel):
    severity: Literal["critical", "warning"]
    issue: str
    affected_bullet: Optional[str] = None
    suggested_fix: str = ""
    fix_step: Literal[
        "workstream", "evidence_matching", "claim_design", "section_story", "writing"
    ] = "writing"


class AuditResult(BaseModel):
    passed: bool
    issues: list[AuditIssue] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Full draft output
# ---------------------------------------------------------------------------


class ResumeTailorDraft(BaseModel):
    """Complete output of the resume tailor pipeline."""
    workstream_analysis: WorkstreamAnalysis = Field(default_factory=WorkstreamAnalysis)
    fact_atoms: list[FactAtom] = Field(default_factory=list)
    experience_workflows: list[ExperienceWorkflow] = Field(default_factory=list)
    evidence_matches: list[EvidenceMatch] = Field(default_factory=list)
    section_plans: list[SectionPlan] = Field(default_factory=list)
    bullet_edits: list[BulletEdit] = Field(default_factory=list)
    revised_resume_markdown: str = ""
    audit: AuditResult = Field(default_factory=lambda: AuditResult(passed=True))

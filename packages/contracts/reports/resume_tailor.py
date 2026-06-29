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


class WorkstreamCapability(BaseModel):
    """A capability tied to a specific workstream."""
    capability: str
    demand_type: Literal[
        "domain_knowledge", "technical_skill", "analytical_capability",
        "workflow_capability", "stakeholder_capability",
        "business_context_knowledge", "operating_judgment", "mixed",
    ] = "mixed"
    importance: Literal["core", "supporting", "nice_to_have"] = "supporting"


class Workstream(BaseModel):
    """A recurring work loop the role performs."""
    name: str
    description: str = ""
    capabilities: list[WorkstreamCapability] = Field(default_factory=list)


class EvidenceRequirement(BaseModel):
    """What the resume must prove for a specific capability."""
    capability: str
    workstream: str = ""
    importance: Literal["core", "supporting", "nice_to_have"] = "supporting"
    evidence_checklist: list[str] = Field(default_factory=list)
    reasoning: str = ""


class WorkstreamAnalysis(BaseModel):
    workstreams: list[Workstream] = Field(default_factory=list)
    evidence_requirements: list[EvidenceRequirement] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Step 3a: Experience story reconstruction (候选人侧 — 还原完整经历)
# ---------------------------------------------------------------------------


class StoryClaim(BaseModel):
    """A specific claim about what the candidate did, with confidence."""
    claim: str
    source_bullets: list[int] = Field(default_factory=list)
    confidence: Literal["stated", "strongly_implied", "inferred"] = "stated"
    basis: str = ""


class ExperienceStory(BaseModel):
    """Reconstructed full picture of what the candidate did in one role."""
    experience_index: int
    employer: str = ""
    title: str = ""
    role_context: str = ""
    narrative: str = ""
    claims: list[StoryClaim] = Field(default_factory=list)
    reconstruction_confidence: Literal["high", "medium", "low"] = "medium"
    gaps: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Step 3b: Fact atoms (从 experience story 提取结构化事实)
# ---------------------------------------------------------------------------


class FactAtom(BaseModel):
    experience_index: int
    source_bullets: list[int] = Field(default_factory=list)
    context: str = ""
    input: str = ""
    action: str = ""
    method: str = ""
    output: str = ""
    stakeholder: str = ""
    impact: str = ""
    boundary: str = ""
    confidence: Literal["stated", "strongly_implied", "inferred"] = "stated"


# ---------------------------------------------------------------------------
# Step 4: Evidence matching
# ---------------------------------------------------------------------------


class EvidenceSource(BaseModel):
    """A single fact atom contributing to an evidence match."""
    fact_atom_index: int
    experience_index: int
    contribution: str = ""


class EvidenceMatch(BaseModel):
    capability: str
    workstream: str = ""
    importance: Literal["core", "supporting", "nice_to_have"] = "supporting"
    strength: Literal["direct", "adjacent", "supporting", "weak", "gap"]
    sources: list[EvidenceSource] = Field(default_factory=list)
    evidence_summary: str = ""
    reasoning: str = ""


# ---------------------------------------------------------------------------
# Step 5: Bullet planning (claim + evidence + framing + edit decision)
# ---------------------------------------------------------------------------


class BulletPlan(BaseModel):
    """Complete design for one bullet position."""
    experience_index: int
    bullet_index: int
    claim: str
    evidence_source_indices: list[int] = Field(default_factory=list)
    evidence_strength: Literal["direct", "adjacent", "supporting"] = "supporting"
    framing_guidance: str = ""
    section_position: Literal[
        "identity", "core_capability", "execution", "impact", "breadth"
    ] = "core_capability"
    original_text: str = ""
    layout_budget: str = ""
    boundary: str = ""


class SectionPlan(BaseModel):
    experience_index: int
    employer: str = ""
    title: str = ""
    story_arc: str = ""
    bullet_plans: list[BulletPlan] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Step 7: Audit
# ---------------------------------------------------------------------------


class AuditIssue(BaseModel):
    severity: Literal["critical", "warning"]
    issue: str
    affected_bullet: Optional[str] = None
    suggested_fix: str = ""
    fix_step: Literal[
        "workstream", "evidence_matching", "bullet_planning", "writing"
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
    experience_stories: list[ExperienceStory] = Field(default_factory=list)
    fact_atoms: list[FactAtom] = Field(default_factory=list)
    evidence_matches: list[EvidenceMatch] = Field(default_factory=list)
    section_plans: list[SectionPlan] = Field(default_factory=list)
    revised_resume_markdown: str = ""
    audit: AuditResult = Field(default_factory=lambda: AuditResult(passed=True))

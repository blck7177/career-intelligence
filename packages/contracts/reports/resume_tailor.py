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
# Step 1.5: Role capability inference — raw material step.
#
# underlying_skill_demands (from job_report) is anchored to explicit JD
# phrases by construction (each entry traces to a jd_phrase) — it structurally
# cannot surface capabilities the role implies but the JD never bothered to
# state. This step reads business_context + daily_workflow + the full JD text
# and independently infers what an experienced practitioner would expect
# beyond the literal posting, the same way Step3a uses a role/company-type
# prior to decompress a candidate's bullets. It deliberately does NOT see
# underlying_skill_demands, to avoid anchoring on an already-finished list
# instead of doing its own reasoning.
#
# This is raw material, not a curated conclusion: generate broadly, tag each
# guess with confidence/importance_hint, and let Step2 (and everything after
# it) decide what's credible enough to use. Compression happens downstream,
# not here.
# ---------------------------------------------------------------------------


class InferredCapability(BaseModel):
    """A capability not explicitly stated in the JD, inferred from role
    archetype + business context + daily workflow + JD texture."""
    capability: str
    demand_type: Literal[
        "domain_knowledge", "technical_skill", "analytical_capability",
        "workflow_capability", "stakeholder_capability",
        "business_context_knowledge", "operating_judgment", "mixed",
    ] = "mixed"
    reasoning: str = ""
    confidence: Literal["high", "medium", "low"] = "medium"
    importance_hint: Literal["core", "supporting", "nice_to_have"] = "supporting"


class RoleCapabilityInference(BaseModel):
    inferred_capabilities: list[InferredCapability] = Field(default_factory=list)


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
    provenance: Literal["stated", "inferred"] = "stated"


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
    """A single piece of evidence contributing to an evidence match.

    fact_atom_index is None when the evidence is story-level only — the
    individual fact atoms for this experience don't capture the capability,
    but the experience_story's narrative as a whole does (e.g. two atoms
    combined prove a capability neither proves alone). experience_index is
    always required so downstream steps can still verify which experience
    the evidence comes from even without a specific atom.
    """
    fact_atom_index: Optional[int] = None
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
# Step 4.5: Resume strategy — the free-thinking step between "what evidence
# exists" (Step4) and "how do we execute it bullet by bullet" (Step5).
#
# Step4 answers an analytical question per capability: how strong is the
# candidate's evidence? This step answers a strategic question once, for the
# whole resume: given all of that evidence together, what's the honest
# argument this resume should make, and how should each capability be used
# (or deliberately not used) to make it? Step5 then executes this plan
# instead of independently re-deciding "should this bullet serve the JD"
# bullet by bullet, which is what let claims quietly default to describing
# the candidate's native strengths instead of the target role.
# ---------------------------------------------------------------------------


class CapabilityStrategy(BaseModel):
    """How one evidence_requirement's capability should be used in the resume."""
    capability: str  # exact match to an evidence_requirements[].capability
    decision: Literal[
        "foreground",       # real strength — lead with it
        "bridge",           # adjacent evidence — needs explicit domain-bridging language
        "minimal_mention",  # weak but worth a passing nod, not a dedicated bullet
        "omit_honest_gap",  # no real evidence — leave it honestly absent, do not imply it
        "ask_candidate",    # story suggests there may be unwritten relevant experience
    ]
    reasoning: str = ""
    note_for_candidate: str = ""  # only meaningful when decision == "ask_candidate"


class SectionSpaceBudget(BaseModel):
    """How much of the resume one experience should occupy, and why."""
    experience_index: int
    employer: str = ""
    bullet_count_target: int
    role_in_argument: str = ""  # e.g. "identity + core capability", "breadth only"


class ResumeStrategy(BaseModel):
    """The single strategic plan that Step5 (bullet planning) executes."""
    overall_fit: Literal["strong_fit", "viable_fit", "stretch_fit", "weak_fit"]
    fit_reasoning: str = ""
    resume_thesis: str = ""  # "after reading this resume, the hiring manager should believe ___"
    capability_strategies: list[CapabilityStrategy] = Field(default_factory=list)
    section_space_budget: list[SectionSpaceBudget] = Field(default_factory=list)
    forbidden_claims: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Step 5: Bullet planning (claim + evidence + framing + edit decision)
# ---------------------------------------------------------------------------

# Sentinel value for BulletPlan.serves_capability: an honest declaration that
# this bullet was NOT designed to prove a target-role capability (e.g. it
# exists purely to establish identity/breadth), instead of leaving the field
# empty/ambiguous or quietly substituting an unrelated capability.
BREADTH_NO_JD_MATCH = "breadth_no_jd_match"


class BulletPlan(BaseModel):
    """Complete design for one bullet position."""
    experience_index: int
    bullet_index: int
    claim: str
    serves_capability: str = Field(
        default="",
        description=(
            "Must exactly match one evidence_requirements[].capability string "
            "this bullet is designed to prove, or the literal sentinel "
            "'breadth_no_jd_match' if no JD capability fits and this bullet "
            "exists purely for identity/breadth purposes."
        ),
    )
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
        "workstream", "fact_extraction", "evidence_matching", "strategy",
        "bullet_planning", "writing",
    ] = "writing"


class AuditResult(BaseModel):
    passed: bool
    issues: list[AuditIssue] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Full draft output
# ---------------------------------------------------------------------------


class ResumeTailorDraft(BaseModel):
    """Complete output of the resume tailor pipeline."""
    role_capability_inference: RoleCapabilityInference = Field(default_factory=RoleCapabilityInference)
    workstream_analysis: WorkstreamAnalysis = Field(default_factory=WorkstreamAnalysis)
    experience_stories: list[ExperienceStory] = Field(default_factory=list)
    fact_atoms: list[FactAtom] = Field(default_factory=list)
    evidence_matches: list[EvidenceMatch] = Field(default_factory=list)
    resume_strategy: ResumeStrategy = Field(
        default_factory=lambda: ResumeStrategy(overall_fit="viable_fit")
    )
    section_plans: list[SectionPlan] = Field(default_factory=list)
    revised_resume_markdown: str = ""
    audit: AuditResult = Field(default_factory=lambda: AuditResult(passed=True))

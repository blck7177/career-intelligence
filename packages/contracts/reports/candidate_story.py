"""
Contracts for the Candidate Story Bank structuring step.

The candidate-story-agent (OpenClaw) produces a free-form investigation
transcript per experience (a Hiring-Manager/Candidate-Advocate interview,
including real web research where the Advocate couldn't answer confidently).

This module defines two things:
  - InvestigationTranscript: the shape of what the agent writes (read by the
    worker, not LLM-validated — the agent writes plain JSON to a file).
  - The structuring output schema (StoryStructuringOutput and friends): used
    with LLMClient.complete_structured() to turn transcripts into the
    persisted story bank. This is a plain, non-agentic LLM call — no tools,
    no OpenClaw — mirroring resume_tailor's Step 3b Fact Extraction pattern.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Agent output (read from investigation_transcript.json)
# ---------------------------------------------------------------------------


class ExperienceTranscript(BaseModel):
    """One experience's Hiring-Manager/Candidate-Advocate interview."""

    experience_ref: str
    employer: str = ""
    title: str = ""
    transcript: str = ""


class InvestigationTranscript(BaseModel):
    """Top-level shape of investigation_transcript.json."""

    experiences: list[ExperienceTranscript] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Structuring step output (produced by LLMClient.complete_structured())
# ---------------------------------------------------------------------------


class StoryEvidenceItem(BaseModel):
    claim: str
    evidence_type: Literal[
        "observed_fact",
        "strongly_implied",
        "plausible_inference",
        "industry_archetype",
        "candidate_question",
    ]
    source_bullets: list[int] = Field(default_factory=list)
    basis: str = ""
    question: str = ""


class StoryWorkflow(BaseModel):
    inputs: list[str] = Field(default_factory=list)
    methods: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    stakeholders: list[str] = Field(default_factory=list)


class CandidateStory(BaseModel):
    experience_ref: str
    story_id: str
    workstream_title: str
    bullets_covered: list[int] = Field(default_factory=list)
    narrative: str = ""
    workflow: StoryWorkflow = Field(default_factory=StoryWorkflow)
    evidence_items: list[StoryEvidenceItem] = Field(default_factory=list)
    candidate_questions: list[str] = Field(default_factory=list)
    do_not_claim: list[str] = Field(default_factory=list)
    research_basis: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Structuring is two passes: extract-and-grade (StorySkeleton, no narrative),
# then narrative-writing from only the highest-grade evidence. Splitting the
# calls means the narrative-writing model physically never sees
# plausible_inference / industry_archetype / candidate_question content, so it
# cannot blend speculation into prose — the same "don't give it the
# temptation" logic as the investigation/structuring split itself.
# ---------------------------------------------------------------------------


class StorySkeleton(BaseModel):
    experience_ref: str
    story_id: str
    workstream_title: str
    bullets_covered: list[int] = Field(default_factory=list)
    workflow: StoryWorkflow = Field(default_factory=StoryWorkflow)
    evidence_items: list[StoryEvidenceItem] = Field(default_factory=list)
    candidate_questions: list[str] = Field(default_factory=list)
    do_not_claim: list[str] = Field(default_factory=list)
    research_basis: list[str] = Field(default_factory=list)


class StorySkeletonOutput(BaseModel):
    stories: list[StorySkeleton] = Field(default_factory=list)


class StoryNarrativeItem(BaseModel):
    experience_ref: str
    story_id: str
    narrative: str = ""


class StoryNarrativeOutput(BaseModel):
    narratives: list[StoryNarrativeItem] = Field(default_factory=list)

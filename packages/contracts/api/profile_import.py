"""
Profile Import contract — LLM structured output schema for resume → profile conversion.

Field names in ProfileImportDraft MUST match ProfileUpdate (apps/api/routes/profile.py)
so the frontend can pass the draft directly to PUT /api/app/profile after user review.

preferences_json is deliberately excluded: resumes indicate what someone has done,
not what they want. Job-search preferences belong in JobDiscoveryFrontendInput.soft_preferences.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class ParseNotes(BaseModel):
    """LLM-reported confidence metadata — shown to the user, never saved to profile."""

    low_confidence_items: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class ResumeExperience(BaseModel):
    """A single work experience entry with preserved bullet points."""
    employer: str = ""
    title: str = ""
    location: str = ""
    start_date: str = ""
    end_date: str = ""
    bullets: list[str] = Field(default_factory=list)


class ResumeEducation(BaseModel):
    institution: str = ""
    degree: str = ""
    graduation_date: str = ""
    coursework: list[str] = Field(default_factory=list)


class ResumeSkillGroup(BaseModel):
    category: str = ""
    items: list[str] = Field(default_factory=list)


class CleanResume(BaseModel):
    """LLM-reconstructed resume — faithful to the original, not synthesized for job search."""

    markdown: str = ""
    experiences: list[ResumeExperience] = Field(default_factory=list)
    education: list[ResumeEducation] = Field(default_factory=list)
    skills: list[ResumeSkillGroup] = Field(default_factory=list)


class ImportProject(BaseModel):
    """Mirrors RepresentativeProject from packages/contracts/profile/candidate.py."""

    title: str = ""
    description: str = ""
    skills_used: list[str] = Field(default_factory=list)
    quantified_impact: str = ""


class ProfileImportDraft(BaseModel):
    """LLM structured output for resume → profile conversion.

    Used as response_schema for LLMClient.complete_structured().
    """

    clean_resume: CleanResume = Field(default_factory=CleanResume)
    summary: str = ""
    experience_summary: str = ""
    education_summary: str = ""
    years_experience: Optional[int] = None
    technical_skills: list[str] = Field(default_factory=list)
    subject_areas: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    representative_projects: list[ImportProject] = Field(default_factory=list)
    parse_notes: ParseNotes = Field(default_factory=ParseNotes)

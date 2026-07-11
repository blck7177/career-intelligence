"""
Adapter: CleanResume (packages.contracts.api.profile_import) -> ResumeDocument.

CleanResume is the real, typed shape resume_tailor's input already comes in
as (profile.structured_resume_json == CleanResume.model_dump()) — see
dev_note/career/phase19-parsing/plan_0710.md for how this was confirmed and
what's deliberately NOT covered here yet:

  - Step6's revised bullet text isn't preserved as structured data anywhere
    in ResumeTailorDraft, only flattened into revised_resume_markdown. Until
    that's fixed upstream (or parsed back out), callers must supply final
    bullet text explicitly via `experience_bullets`; this adapter does not
    read revised_resume_markdown itself.
  - name/contact_line have no known home in the current contracts, so they're
    required arguments here rather than sourced automatically.
"""

from __future__ import annotations

from packages.contracts.api.profile_import import CleanResume

from .schema import ResumeDocument, ResumeEntry, ResumeSection


def from_clean_resume(
    clean_resume: CleanResume,
    name: str,
    contact_line: str,
    headline: str = "",
    summary: str = "",
    experience_bullets: dict[int, list[str]] | None = None,
    extra_sections: list[ResumeSection] | None = None,
) -> ResumeDocument:
    """
    extra_sections are inserted between Key Skills and Professional Experience
    (e.g. a "Project Experience" section) — the current resume_tailor pipeline
    has no data model for these (see plan_0710.md), so callers must build them
    by hand for now.
    """
    experience_bullets = experience_bullets or {}
    sections: list[ResumeSection] = []

    if summary:
        sections.append(ResumeSection(heading="Summary", paragraphs=[summary]))

    if clean_resume.skills:
        sections.append(
            ResumeSection(
                heading="Key Skills",
                paragraphs=[
                    f"**{group.category}:** {', '.join(group.items)}"
                    for group in clean_resume.skills
                    if group.category or group.items
                ],
            )
        )

    if extra_sections:
        sections.extend(extra_sections)

    if clean_resume.experiences:
        entries = []
        for idx, exp in enumerate(clean_resume.experiences):
            dates = f"{exp.start_date} - {exp.end_date}" if exp.start_date or exp.end_date else ""
            subtitle = " | ".join(part for part in (exp.employer, exp.location) if part)
            entries.append(
                ResumeEntry(
                    title_line=exp.title,
                    dates=dates,
                    subtitle_line=subtitle,
                    bullets=experience_bullets.get(idx, exp.bullets),
                )
            )
        sections.append(ResumeSection(heading="Professional Experience", entries=entries))

    if clean_resume.education:
        bullets = []
        for edu in clean_resume.education:
            parts = [p for p in (edu.institution, edu.degree) if p]
            line = " — ".join(parts)
            if edu.graduation_date:
                line += f", {edu.graduation_date}"
            if edu.coursework:
                line += ". " + ", ".join(edu.coursework)
            bullets.append(line)
        sections.append(ResumeSection(heading="Education", bullets=bullets))

    return ResumeDocument(
        name=name,
        contact_line=contact_line,
        headline=headline,
        sections=sections,
    )

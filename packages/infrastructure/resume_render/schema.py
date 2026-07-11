"""
Content schema for rendering a resume into a formatted document.

Deliberately decoupled from the resume_tailor pipeline's own contracts
(packages/contracts/reports/resume_tailor.py): this module only needs
visible text, not evidence/strategy/framing fields. Callers adapt
SectionPlan/BulletPlan into a ResumeDocument before rendering.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ResumeEntry:
    """One role/position within a section (title + dates, optional org line, bullets)."""

    title_line: str
    dates: str = ""
    subtitle_line: str = ""
    bullets: list[str] = field(default_factory=list)


@dataclass
class ResumeSection:
    """
    A top-level resume section. Use whichever of paragraphs/entries/bullets
    fits the section's shape:
      - paragraphs: prose blocks (Summary, Key Skills). A paragraph may start
        with a "**bold lead-in**" span (e.g. "**Systematic Trading:** ...").
      - entries: role/position blocks with a title+dates line (Experience).
      - bullets: a flat bullet list with no entry wrapper (Education).
    """

    heading: str
    paragraphs: list[str] = field(default_factory=list)
    entries: list[ResumeEntry] = field(default_factory=list)
    bullets: list[str] = field(default_factory=list)


@dataclass
class ResumeDocument:
    name: str
    contact_line: str
    headline: str = ""
    sections: list[ResumeSection] = field(default_factory=list)

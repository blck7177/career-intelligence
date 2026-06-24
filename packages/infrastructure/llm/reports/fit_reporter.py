"""
FitReporter — LLM-based Candidate Fit Report generation.

Migrated from career-openclaw/src/career_intelligence/services/match_service.py.

Changes from original:
  - Uses complete_structured() instead of manual JSON parse + _extract_json()
  - _build_narrative() reads from FitReportStructured Pydantic object
  - No MetadataStore, no workspace paths, no RequestContext
  - Public API: generate_fit_report() -> (FitReportStructured, narrative_md)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from packages.contracts.reports.fit_report import FitReportStructured

FIT_PROMPT_VERSION = "0.1.0"

_SYSTEM_PROMPT = """\
You are a senior career advisor specialising in finance and risk roles at investment banks, \
asset managers, and financial institutions. Your task is to analyse how well a candidate's \
experience and skills match a specific role, based on a deep job intelligence report.

Be specific and evidence-based. When citing strong matches, reference the candidate's actual \
projects and skills. When identifying gaps, be concrete about what is missing and why it matters.

Output only valid JSON — no markdown fences, no explanation outside the JSON object.\
"""


def _build_user_prompt(
    job_record: dict[str, Any],
    structured_job_report: dict[str, Any],
    candidate_profile: dict[str, Any],
    fit_report_id: str,
    job_report_id: str,
    workspace_id: str,
    profile_id: str,
) -> str:
    now = datetime.now(timezone.utc).isoformat()

    projects_text = ""
    for i, proj in enumerate(candidate_profile.get("representative_projects", []), 1):
        title = proj.get("title", f"Project {i}")
        desc = proj.get("description", "")
        skills = ", ".join(proj.get("skills_used", []))
        impact = proj.get("quantified_impact", "")
        projects_text += f"\n  {i}. {title}\n     Description: {desc}\n     Skills used: {skills}"
        if impact:
            projects_text += f"\n     Impact: {impact}"

    return f"""\
## Role Overview
Title: {job_record.get('title', 'Unknown')}
Company: {job_record.get('company', 'Unknown')}
Workstream: {job_record.get('primary_workstream', 'Unknown')}
Location: {job_record.get('location', 'Unknown')}

## Job Intelligence Report (structured analysis)
{json.dumps(structured_job_report, ensure_ascii=False, indent=2)}

## Candidate Profile
Years of experience: {candidate_profile.get('years_experience', 'Unknown')}
Background: {candidate_profile.get('summary', '')}
Domain experience: {', '.join(candidate_profile.get('domain_experience', []))}
Technical skills: {', '.join(candidate_profile.get('technical_skills', []))}
Finance domains: {', '.join(candidate_profile.get('finance_domains', []))}
Tools: {', '.join(candidate_profile.get('tools', []))}

Key projects:{projects_text}

## Output Requirements

Return a single JSON object with these exact fields:

{{
  "fit_report_id": "{fit_report_id}",
  "workspace_id": "{workspace_id}",
  "job_id": "{job_record.get('job_id', '')}",
  "job_report_id": "{job_report_id}",
  "candidate_profile_id": "{profile_id}",
  "analyzed_at": "{now}",
  "prompt_version": "{FIT_PROMPT_VERSION}",

  "overall_match_score": <integer 0-100, alignment signal — not a hiring prediction>,
  "match_summary": "<2-3 sentences summarising fit and key gaps>",

  "strong_matches": [
    {{"demand": "<role requirement>", "evidence": "<specific evidence from candidate profile>"}}
  ],

  "partial_matches": [
    {{"demand": "<role requirement>", "gap_description": "<what the candidate has vs what is needed>"}}
  ],

  "gaps": [
    {{
      "demand": "<role requirement>",
      "gap_description": "<what is missing>",
      "severity": "<blocking|significant|minor>"
    }}
  ],

  "risk_flags": [
    "<string — e.g. title mismatch, missing licence, seniority bar>"
  ],

  "interview_talking_points": [
    "<3-4 concrete angles the candidate should prepare to discuss>"
  ],

  "resume_rewrite_strategy": {{
    "positioning": "<how to frame the candidate's overall story for this specific role>",
    "keywords_to_add": ["<JD term missing from candidate's visible skill set>"],
    "bullets_to_reframe": [],
    "evidence_to_surface": ["<project or experience that should be made more prominent>"]
  }},

  "recommended_next_action": "<one of: apply now | revise resume first | get more context | skip>"
}}

Rules:
- strong_matches must cite specific project names or skills from the candidate profile.
- gaps severity: 'blocking' = role cannot proceed without it; 'significant' = real weakness; 'minor' = nice-to-have.
- bullets_to_reframe must always be an empty array [] — no resume bullets are available yet.
- overall_match_score: 80+ means strong alignment; 60-79 good with addressable gaps; below 60 significant gaps.\
"""


def _build_narrative(structured: FitReportStructured) -> str:
    """Build a lightweight markdown narrative from a FitReportStructured Pydantic object."""
    score = structured.overall_match_score
    summary = structured.match_summary
    action = structured.recommended_next_action

    lines = [
        "# Candidate Fit Report",
        "",
        f"**Match Score:** {score}/100  |  **Recommended action:** {action}",
        "",
        "## Summary",
        summary,
        "",
    ]

    strong = structured.strong_matches
    if strong:
        lines += ["## Strong Matches", ""]
        for m in strong:
            lines.append(f"- **{m.demand}** — {m.evidence}")
        lines.append("")

    partial = structured.partial_matches
    if partial:
        lines += ["## Partial Matches", ""]
        for m in partial:
            lines.append(f"- **{m.demand}** — {m.gap_description}")
        lines.append("")

    gaps = structured.gaps
    if gaps:
        lines += ["## Gaps", ""]
        for g in gaps:
            lines.append(f"- [{g.severity.upper()}] **{g.demand}** — {g.gap_description}")
        lines.append("")

    flags = structured.risk_flags
    if flags:
        lines += ["## Risk Flags", ""]
        for f in flags:
            lines.append(f"- \u26a0 {f}")
        lines.append("")

    points = structured.interview_talking_points
    if points:
        lines += ["## Interview Talking Points", ""]
        for i, p in enumerate(points, 1):
            lines.append(f"{i}. {p}")
        lines.append("")

    strategy = structured.resume_rewrite_strategy
    if strategy:
        lines += ["## Resume Positioning Guidance", ""]
        if strategy.positioning:
            lines += [f"**Positioning:** {strategy.positioning}", ""]
        if strategy.keywords_to_add:
            lines += ["**Keywords to add:** " + ", ".join(f"`{k}`" for k in strategy.keywords_to_add), ""]
        if strategy.evidence_to_surface:
            lines += ["**Evidence to surface:**", ""]
            for e in strategy.evidence_to_surface:
                lines.append(f"- {e}")
            lines.append("")

    return "\n".join(lines)


def generate_fit_report(
    job_record: dict,
    structured_job_report: dict,
    candidate_profile: dict,
    *,
    fit_report_id: str,
    job_report_id: str,
    workspace_id: str,
    profile_id: str,
    llm_client,
) -> tuple[FitReportStructured, str]:
    """
    Call LLM to generate fit report.
    Returns (structured_fit_report, narrative_markdown).
    """
    user_prompt = _build_user_prompt(
        job_record=job_record,
        structured_job_report=structured_job_report,
        candidate_profile=candidate_profile,
        fit_report_id=fit_report_id,
        job_report_id=job_report_id,
        workspace_id=workspace_id,
        profile_id=profile_id,
    )
    structured = llm_client.complete_structured(
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        response_schema=FitReportStructured,
        max_tokens=4096,
    )
    narrative = _build_narrative(structured)
    return structured, narrative

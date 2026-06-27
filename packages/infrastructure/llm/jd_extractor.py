"""
JD Structured Extractor — extracts key fields from raw JD text via LLM.

Called during job discovery (search_run._persist_candidates) to provide
structured JD data for the frontend before a full Job Report is generated.

Uses OpenAI Structured Outputs (complete_structured) for guaranteed schema
compliance — no manual JSON parsing or retry logic needed.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from pydantic import BaseModel, Field

from .client import LLMClient, LLMCallError

logger = logging.getLogger(__name__)

_MAX_JD_CHARS = 15000

_SYSTEM_PROMPT = """\
You are a structured job description extractor.

Rules:
1. Extract only information explicitly stated or strongly implied by the JD.
2. For inferred fields (likely_tasks, likely_stakeholders, inferred_team_context), \
you may infer from context but stay grounded in the JD text.
3. If a field cannot be extracted, use an empty list [] or empty string "".
4. seniority_inferred: infer from title or requirements. Use one of: \
junior, mid, senior, lead, director, executive, unknown.
5. Be concise — each list item should be a short phrase, not a paragraph.
"""

_USER_TEMPLATE = """\
Extract structured fields from this job description.

<job_metadata>
Company: {company}
Title: {title}
Location: {location}
</job_metadata>

<jd_text>
{jd_text}
</jd_text>
"""


class JDExtraction(BaseModel):
    responsibilities: list[str] = Field(default_factory=list)
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    tools_mentioned: list[str] = Field(default_factory=list)
    seniority_inferred: str = "unknown"
    likely_tasks: list[str] = Field(default_factory=list)
    likely_stakeholders: list[str] = Field(default_factory=list)
    inferred_team_context: str = ""
    role_category: Optional[str] = None


def _clean_jd_text(raw: str) -> str:
    """Strip web boilerplate (CSS, nav, HTML tags) to surface the real JD content."""
    text = raw
    text = re.sub(r"@font-face\s*\{[^}]*\}", "", text)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
    text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\{[^}]{20,}\}", " ", text)
    lines = text.splitlines()
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if len(stripped) < 3:
            continue
        if stripped.startswith(("http://", "https://", "/*", "*/")):
            continue
        cleaned.append(stripped)
    return "\n".join(cleaned)


def extract_jd_fields(
    jd_text: str,
    company: str,
    title: str,
    location: str = "",
    llm_client: LLMClient | None = None,
) -> dict:
    """
    Extract structured fields from raw JD text.

    Returns a dict suitable for merging into raw_payload_json.
    On failure, returns a dict with empty fields and an _extraction_error key.
    """
    if llm_client is None:
        from .client import get_llm_client
        llm_client = get_llm_client()

    if not jd_text or len(jd_text.strip()) < 50:
        return _empty_result("JD text too short for extraction")

    cleaned = _clean_jd_text(jd_text)
    if len(cleaned.strip()) < 50:
        return _empty_result("JD text too short after cleaning")

    user_prompt = _USER_TEMPLATE.format(
        company=company,
        title=title,
        location=location or "N/A",
        jd_text=cleaned[:_MAX_JD_CHARS],
    )

    try:
        result = llm_client.complete_structured(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            response_schema=JDExtraction,
            max_tokens=2048,
            temperature=0.2,
        )
        logger.info("JD extraction succeeded for %s at %s", title, company)
        return result.model_dump()
    except LLMCallError as exc:
        logger.warning("JD extraction failed for %s at %s: %s", title, company, exc)
        return _empty_result(str(exc))
    except Exception as exc:
        logger.warning("JD extraction unexpected error: %s", exc)
        return _empty_result(str(exc))


def _empty_result(reason: str = "") -> dict:
    data = JDExtraction().model_dump()
    data["_extraction_error"] = reason
    return data

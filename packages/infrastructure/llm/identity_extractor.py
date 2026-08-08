"""
Job identity extractor — reads title/company/location off a job posting page
whose markup gave us nothing structured.

This is the *general* identity channel, and the reason it exists is that every
other one is site-specific: the ATS board APIs cover known vendors, the
schema.org tier covers pages that publish JobPosting markup, and between them
sits the long tail of employer-built career portals that render a perfectly
readable page with no machine-readable identity anywhere in it (higher.gs.com:
Next.js, server-rendered, real JD in the HTML, zero JSON-LD).

What used to fill that gap was a guess at the URL string — slug -> title,
hostname -> company — which produced rows like "169151" at "Higher". A guess
cannot fail loudly, so a page we could not read became a row nobody could tell
was wrong. This module replaces guessing with reading, and reading can fail:
callers get None and are expected to refuse the import rather than invent a row.

Anti-fabrication: the model's answer is not trusted on its own. Every field is
checked back against the page text and dropped if it isn't actually there (see
_verify_verbatim / _verify_tokens). A model that paraphrases a title, expands
an abbreviation, or supplies a plausible employer name for an unbranded page
fails that check — the failure mode this guards is exactly the one the URL
guess had, so it must not be reintroduced by way of the LLM.
"""

from __future__ import annotations

import logging
import os
import re
import unicodedata

from pydantic import BaseModel, Field

from .client import LLMCallError, LLMClient

logger = logging.getLogger(__name__)

# Identity lives at the top of a posting — title, employer, location are in the
# page head/masthead long before the responsibilities start. Feeding the whole
# JD would cost tokens for text that cannot contain the answer.
_MAX_PAGE_CHARS = 6000

# Cheapest current OpenAI model; this is a short read of plain text against a
# three-field schema, and the evidence gate below catches a weak model's
# mistakes rather than the model being asked to be trustworthy on its own.
_DEFAULT_IDENTITY_MODEL = "gpt-5.4-nano"

_SYSTEM_PROMPT = """\
You read a job posting page and report the posting's identity.

Rules:
1. Copy values VERBATIM from the page text. Do not paraphrase, reformat, \
expand abbreviations, or fix capitalization.
2. Report only what the page states. If the page does not state a field, \
return null for it. A null is always better than a guess.
3. title: the job title alone. Strip site branding and separators the page \
appends to it (e.g. "| Acme Corp", "- Careers"), and strip a location suffix \
only if the title clearly repeats it.
4. company: the employer doing the hiring — not the job board, ATS vendor, or \
website name. If the page only shows a website/brand and never names an \
employer, return null.
5. location: the work location as written on the page.
"""

_USER_TEMPLATE = """\
Report the identity of the job posting on this page.

<page_url>
{url}
</page_url>

<page_text>
{page_text}
</page_text>
"""


class JobIdentity(BaseModel):
    """Identity as read off the page. Every field is optional — an absent field
    is a real answer ("the page does not say"), not a failure to comply."""

    title: str | None = Field(default=None)
    company: str | None = Field(default=None)
    location: str | None = Field(default=None)


def _normalize_for_match(text: str) -> str:
    """Fold the differences that are not the model inventing something.

    Case, unicode punctuation (curly quotes, en/em dashes, non-breaking
    spaces), and whitespace runs all vary between how a page renders a string
    and how a model transcribes it. Everything else — a different word, an
    expanded abbreviation, a supplied employer name — survives normalization
    and gets caught.
    """
    folded = unicodedata.normalize("NFKC", text)
    folded = folded.translate(
        str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"',
                       "–": "-", "—": "-", "−": "-"})
    )
    return re.sub(r"\s+", " ", folded).strip().lower()


def _verify_verbatim(value: str | None, haystack_norm: str) -> str | None:
    """Keep `value` only if it appears on the page; otherwise drop it."""
    if not value or not value.strip():
        return None
    candidate = value.strip()
    if _normalize_for_match(candidate) in haystack_norm:
        return candidate
    logger.info("identity gate: rejected value absent from page text: %r", candidate[:120])
    return None


def _verify_tokens(value: str | None, haystack_norm: str) -> str | None:
    """Token-level check, for location only.

    A location is assembled as often as it is quoted — a page saying "New York,
    New York, United States" legitimately yields "New York, NY". Requiring the
    whole string verbatim would reject those, so require instead that every
    word it is built from is on the page. That still blocks a city the page
    never mentions, which is the fabrication worth stopping.
    """
    if not value or not value.strip():
        return None
    candidate = value.strip()
    words = [w for w in re.findall(r"[^\W\d_]+", candidate, flags=re.UNICODE) if len(w) >= 3]
    if not words:
        # Nothing checkable (e.g. "NY", "UK") — no evidence either way, so this
        # is the one place a value passes unverified. Low stakes: location is
        # never an identity key, only display.
        return candidate
    if all(_normalize_for_match(w) in haystack_norm for w in words):
        return candidate
    logger.info("identity gate: rejected location absent from page text: %r", candidate[:120])
    return None


def extract_job_identity(
    *,
    page_text: str,
    url: str,
    llm_client: LLMClient | None = None,
) -> JobIdentity | None:
    """Read title/company/location off a posting page.

    Returns None when identity could not be established — the model failed, or
    everything it produced failed the evidence gate. A returned JobIdentity may
    still carry None fields (the page genuinely doesn't say); only `title` is
    load-bearing for the caller, since a row without one cannot be labelled.

    Never raises: an LLM outage degrades to "identity unknown", which the
    caller turns into an honest refusal rather than a fabricated row.
    """
    if not page_text or not page_text.strip():
        return None

    if llm_client is None:
        from .client import get_llm_client

        llm_client = get_llm_client()

    model = os.environ.get("LLM_IDENTITY_MODEL", _DEFAULT_IDENTITY_MODEL)

    try:
        raw = llm_client.complete_structured(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=_USER_TEMPLATE.format(url=url, page_text=page_text[:_MAX_PAGE_CHARS]),
            response_schema=JobIdentity,
            model=model,
            max_tokens=2048,
            temperature=0.0,
        )
    except LLMCallError as exc:
        logger.warning("identity extraction failed for %s: %s", url, exc)
        return None
    except Exception:
        logger.warning("identity extraction unexpected error for %s", url, exc_info=True)
        return None

    # Verify against the whole page, not just the slice the model saw: the
    # claim being checked is "this string is on the page", and a title quoted
    # from the masthead may repeat further down.
    haystack = _normalize_for_match(page_text)
    verified = JobIdentity(
        title=_verify_verbatim(raw.title, haystack),
        company=_verify_verbatim(raw.company, haystack),
        location=_verify_tokens(raw.location, haystack),
    )

    if not any((verified.title, verified.company, verified.location)):
        logger.info("identity extraction produced nothing verifiable for %s", url)
        return None

    logger.info(
        "identity extraction for %s: title=%r company=%r location=%r",
        url, verified.title, verified.company, verified.location,
    )
    return verified

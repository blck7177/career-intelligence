"""Tests for the LLM job-identity channel.

The channel exists because the URL-guess it replaced could not fail — it always
produced *something*, so an unreadable page became an unmarked wrong row. What
matters here is therefore mostly the failure directions: the evidence gate must
drop anything the page doesn't actually say, and the extractor must return None
rather than a plausible answer when it can't do better.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from packages.infrastructure.llm.client import LLMCallError
from packages.infrastructure.llm.identity_extractor import (
    JobIdentity,
    _normalize_for_match,
    _verify_tokens,
    _verify_verbatim,
    extract_job_identity,
)

# Shaped like the real thing this was built for: higher.gs.com, where the title
# is in the page masthead and the employer only appears via site branding.
_PAGE = (
    "Asset & Wealth Management, MAS, PM Infrastructure and AI Data Strategy, "
    "Associate - New York | Goldman Sachs\n\n"
    "location_on  New York, New York, United States\n\n"
    "Apply\n\n"
    "Responsibilities:\n\nBuild deep domain fluency across MAS portfolio "
    "management, trading, risk, and PM Infrastructure.\n"
)


def _client(identity: JobIdentity):
    client = MagicMock()
    client.complete_structured.return_value = identity
    return client


class TestEvidenceGate:
    """The gate is the whole reason an LLM is allowed near this field at all."""

    def test_verbatim_value_survives(self):
        page = _normalize_for_match(_PAGE)
        assert _verify_verbatim("Goldman Sachs", page) == "Goldman Sachs"

    def test_invented_value_is_dropped(self):
        page = _normalize_for_match(_PAGE)
        assert _verify_verbatim("Goldman Sachs Group Inc.", page) is None
        assert _verify_verbatim("Quantitative Analyst", page) is None

    def test_case_punctuation_and_whitespace_differences_survive(self):
        # Folding these is not leniency about content — they are transcription
        # artifacts, not different words.
        page = _normalize_for_match("Senior  Risk Analyst — Markets  Team")
        assert _verify_verbatim("senior risk analyst - markets team", page) is not None
        assert _verify_verbatim("Senior Risk Analyst – Markets Team", page) is not None

    def test_empty_and_blank_are_dropped(self):
        page = _normalize_for_match(_PAGE)
        assert _verify_verbatim(None, page) is None
        assert _verify_verbatim("   ", page) is None

    def test_a_word_changed_is_caught(self):
        # The near-miss is the case that matters: one substituted word is what
        # a paraphrasing model produces, and it must not pass.
        page = _normalize_for_match("Senior Risk Analyst")
        assert _verify_verbatim("Senior Risk Manager", page) is None


class TestLocationTokenGate:
    """Locations get assembled rather than quoted, so the gate is by word —
    still enough to block a city the page never mentions."""

    def test_assembled_location_passes(self):
        page = _normalize_for_match("location_on New York, New York, United States")
        assert _verify_tokens("New York, NY", page) == "New York, NY"

    def test_absent_city_is_dropped(self):
        page = _normalize_for_match("location_on New York, New York, United States")
        assert _verify_tokens("San Francisco, CA", page) is None

    def test_partially_present_location_is_dropped(self):
        page = _normalize_for_match("New York, United States")
        assert _verify_tokens("New York, Ontario", page) is None

    def test_uncheckable_short_token_passes(self):
        # Nothing ≥3 chars to check; location is display-only, never a key.
        assert _verify_tokens("NY", _normalize_for_match("New York")) == "NY"


class TestExtractJobIdentity:
    def test_reads_identity_off_the_page(self):
        client = _client(JobIdentity(
            title="Asset & Wealth Management, MAS, PM Infrastructure and AI Data "
                  "Strategy, Associate - New York",
            company="Goldman Sachs",
            location="New York, New York, United States",
        ))
        result = extract_job_identity(page_text=_PAGE, url="https://higher.gs.com/roles/169151",
                                      llm_client=client)

        assert result is not None
        assert result.title.startswith("Asset & Wealth Management")
        assert result.company == "Goldman Sachs"
        assert result.location == "New York, New York, United States"

    def test_hallucinated_fields_are_stripped_not_returned(self):
        client = _client(JobIdentity(title="Asset & Wealth Management, MAS, PM "
                                           "Infrastructure and AI Data Strategy, "
                                           "Associate - New York",
                                     company="Morgan Stanley",   # not on the page
                                     location="Chicago, IL"))    # not on the page
        result = extract_job_identity(page_text=_PAGE, url="https://x.com/1", llm_client=client)

        assert result is not None
        assert result.title is not None
        assert result.company is None
        assert result.location is None

    def test_returns_none_when_nothing_verifies(self):
        client = _client(JobIdentity(title="Chief Robot Officer", company="Initech"))
        assert extract_job_identity(page_text=_PAGE, url="https://x.com/1",
                                    llm_client=client) is None

    def test_returns_none_when_model_reports_nothing(self):
        client = _client(JobIdentity())
        assert extract_job_identity(page_text=_PAGE, url="https://x.com/1",
                                    llm_client=client) is None

    def test_llm_failure_returns_none_never_raises(self):
        client = MagicMock()
        client.complete_structured.side_effect = LLMCallError("429 insufficient_quota")
        assert extract_job_identity(page_text=_PAGE, url="https://x.com/1",
                                    llm_client=client) is None

    def test_unexpected_error_returns_none_never_raises(self):
        client = MagicMock()
        client.complete_structured.side_effect = RuntimeError("socket closed")
        assert extract_job_identity(page_text=_PAGE, url="https://x.com/1",
                                    llm_client=client) is None

    def test_empty_page_short_circuits_without_a_call(self):
        client = MagicMock()
        assert extract_job_identity(page_text="", url="https://x.com/1", llm_client=client) is None
        client.complete_structured.assert_not_called()

    def test_only_the_head_of_the_page_is_sent(self):
        client = _client(JobIdentity(title="Senior Risk Analyst"))
        page = "Senior Risk Analyst\n" + ("filler text about the role. " * 5000)
        extract_job_identity(page_text=page, url="https://x.com/1", llm_client=client)

        sent = client.complete_structured.call_args.kwargs["user_prompt"]
        assert len(sent) < 8000  # 6K page slice + template
        assert "Senior Risk Analyst" in sent

    def test_verification_uses_the_whole_page_not_just_the_slice(self):
        # A value quoted from deep in a long page is still on the page; the gate
        # checks the claim, not the slice the model happened to read.
        client = _client(JobIdentity(title="Senior Risk Analyst", company="Deepco Holdings"))
        page = "Senior Risk Analyst\n" + ("filler. " * 3000) + "\nDeepco Holdings\n"
        result = extract_job_identity(page_text=page, url="https://x.com/1", llm_client=client)

        assert result is not None and result.company == "Deepco Holdings"

    def test_uses_the_cheap_model_by_default(self):
        client = _client(JobIdentity(title="Senior Risk Analyst"))
        extract_job_identity(page_text="Senior Risk Analyst", url="https://x.com/1",
                             llm_client=client)

        assert client.complete_structured.call_args.kwargs["model"] == "gpt-5.4-nano"

    def test_model_is_overridable_by_env(self, monkeypatch):
        monkeypatch.setenv("LLM_IDENTITY_MODEL", "gpt-5.4-mini")
        client = _client(JobIdentity(title="Senior Risk Analyst"))
        extract_job_identity(page_text="Senior Risk Analyst", url="https://x.com/1",
                             llm_client=client)

        assert client.complete_structured.call_args.kwargs["model"] == "gpt-5.4-mini"

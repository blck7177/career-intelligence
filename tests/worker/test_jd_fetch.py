"""
Unit tests for JD fetch service and discovery job persistence.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from packages.contracts.agents.manifests import DiscoveryManifest
from packages.infrastructure.jd_fetch.service import (
    MIN_JD_TEXT_LEN,
    _MAX_RAW_BYTES,
    compute_jd_hash,
    compute_url_hash,
    fetch_jd_from_url,
    resolve_jd,
    save_fetched_jd_artifact,
    strip_html,
)


SAMPLE_HTML = f"""
<html><head><title>Job</title></head><body>
<h1>Market Risk Analyst</h1>
<p>{'We need a strong candidate. ' * 30}</p>
</body></html>
"""


class TestStripHtml:
    def test_removes_tags(self):
        text = strip_html(SAMPLE_HTML)
        assert "<html>" not in text
        assert "Market Risk Analyst" in text
        assert len(text) >= MIN_JD_TEXT_LEN


class TestComputeHashes:
    def test_url_hash_stable(self):
        assert compute_url_hash("https://example.com/job/1") == compute_url_hash(
            "https://example.com/job/1"
        )

    def test_jd_hash_is_16_chars(self):
        h = compute_jd_hash("hello world")
        assert len(h) == 16


class TestFetchJdFromUrl:
    def test_success_html(self):
        response = httpx.Response(200, text=SAMPLE_HTML, request=httpx.Request("GET", "https://x.com"))
        with patch("packages.infrastructure.jd_fetch.service.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = response
            result = fetch_jd_from_url("https://example.com/job/1")

        assert result.ok is True
        assert result.jd_text is not None
        assert result.jd_hash == compute_jd_hash(result.jd_text)
        assert result.source == "worker_fetch"

    def test_http_404(self):
        request = httpx.Request("GET", "https://example.com/missing")
        response = httpx.Response(404, request=request)
        with patch("packages.infrastructure.jd_fetch.service.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.side_effect = httpx.HTTPStatusError(
                "404", request=request, response=response
            )
            result = fetch_jd_from_url("https://example.com/missing")

        assert result.ok is False
        assert "404" in (result.error or "")

    def test_too_short_content(self):
        response = httpx.Response(200, text="<html><body>hi</body></html>", request=httpx.Request("GET", "https://x.com"))
        with patch("packages.infrastructure.jd_fetch.service.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = response
            result = fetch_jd_from_url("https://example.com/short")

        assert result.ok is False
        assert result.fetch_status == "too_short"


_GREENHOUSE_BOARD_RESPONSE = {
    "jobs": [
        {
            "absolute_url": "https://boards.greenhouse.io/acme/jobs/123",
            "title": "Market Risk Analyst",
            "company_name": "Acme",
            "location": {"name": "New York, NY"},
            "content": "<p>" + ("Real job description text. " * 30) + "</p>",
        }
    ]
}


class TestFetchViaAtsApi:
    """fetch_jd_from_url prefers the ATS's structured API over scraping when
    the URL matches a known board — see _fetch_via_ats_api."""

    def test_resolves_via_ats_api_when_url_matches_known_board(self):
        api_response = httpx.Response(
            200,
            json=_GREENHOUSE_BOARD_RESPONSE,
            request=httpx.Request("GET", "https://boards-api.greenhouse.io/v1/boards/acme/jobs"),
        )
        with patch("packages.infrastructure.jd_fetch.service.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = api_response
            result = fetch_jd_from_url("https://boards.greenhouse.io/acme/jobs/123")

        assert result.ok is True
        assert result.source == "ats_api"
        assert "Real job description text" in (result.jd_text or "")
        # Only the ATS API call happened — no fallback scrape of the raw page.
        assert mock_client.return_value.__enter__.return_value.get.call_count == 1

    def test_falls_back_to_scrape_when_ats_api_errors(self):
        with patch("packages.infrastructure.jd_fetch.service.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.side_effect = [
                httpx.ConnectError("boom"),
                httpx.Response(200, text=SAMPLE_HTML, request=httpx.Request("GET", "https://x.com")),
            ]
            result = fetch_jd_from_url("https://boards.greenhouse.io/acme/jobs/999")

        assert result.ok is True
        assert result.source == "worker_fetch"
        assert mock_client.return_value.__enter__.return_value.get.call_count == 2

    def test_falls_back_to_scrape_when_job_not_in_board_listing(self):
        api_response = httpx.Response(
            200,
            json=_GREENHOUSE_BOARD_RESPONSE,
            request=httpx.Request("GET", "https://boards-api.greenhouse.io/v1/boards/acme/jobs"),
        )
        scrape_response = httpx.Response(200, text=SAMPLE_HTML, request=httpx.Request("GET", "https://x.com"))
        with patch("packages.infrastructure.jd_fetch.service.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.side_effect = [api_response, scrape_response]
            # Valid greenhouse-pattern URL, but this job ID isn't in the board's listing.
            result = fetch_jd_from_url("https://boards.greenhouse.io/acme/jobs/000000")

        assert result.ok is True
        assert result.source == "worker_fetch"
        assert mock_client.return_value.__enter__.return_value.get.call_count == 2

    def test_non_ats_url_skips_api_call_entirely(self):
        with patch("packages.infrastructure.jd_fetch.service.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = httpx.Response(
                200, text=SAMPLE_HTML, request=httpx.Request("GET", "https://x.com")
            )
            result = fetch_jd_from_url("https://example.com/careers/job/1")

        assert result.ok is True
        assert result.source == "worker_fetch"
        # Exactly one httpx call (the scrape) — no ATS API attempt for a non-ATS URL.
        assert mock_client.return_value.__enter__.return_value.get.call_count == 1


_EMBED_PAGE = """
<html><head><title>Career Opportunities | Acme</title></head><body>
<div id="grnhse_app"></div>
<script src="https://boards.greenhouse.io/embed/job_board/js?for=acmeboard"></script>
</body></html>
"""

# Greenhouse ships `content` HTML-escaped; the board parser unescapes it.
_EMBED_JOB = {
    "id": 6107228004,
    "absolute_url": "https://www.acme.com/careers/post?gh_jid=6107228004",
    "title": "Quantitative Investment Risk Professional ",  # trailing space is real
    "company_name": "Careers at Acme",
    "location": {"name": "New York, New York, United States"},
    "first_published": "2026-07-02T16:00:48-04:00",
    "content": "&lt;p&gt;" + ("Own the enterprise risk framework. " * 20) + "&lt;/p&gt;",
}

_EMBED_URL = "https://www.acme.com/careers/post?gh_jid=6107228004"

# Same page, but the weight of a real CMS build: the embed <script> lands well
# past _MAX_RAW_BYTES. Measured on the page that exposed this — 236,830 chars
# with the token at 236,743.
_HEAVY_EMBED_PAGE = (
    "<html><head><title>Career Opportunities | Acme</title></head><body>"
    "<div>Skip to main content Partners Careers Contact Log in</div>"
    + "<p>Filler copy in the page shell. </p>" * 6000
    + '<div id="grnhse_app"></div>'
    '<script src="https://boards.greenhouse.io/embed/job_board/js?for=acmeboard"></script>'
    "</body></html>"
)


class TestGreenhouseEmbed:
    """A company careers page that mounts a Greenhouse board client-side: the
    JD is absent from the HTML and the board token is only in the embed script,
    so extract_board_info() sees nothing — see _fetch_via_greenhouse_embed."""

    @staticmethod
    def _api_response(payload=None, status=200):
        return httpx.Response(
            status,
            json=payload if payload is not None else _EMBED_JOB,
            request=httpx.Request("GET", "https://boards-api.greenhouse.io/v1/boards/acmeboard/jobs/1"),
        )

    def _page_response(self, html=_EMBED_PAGE):
        return httpx.Response(200, text=html, request=httpx.Request("GET", _EMBED_URL))

    def test_resolves_jd_and_identity_from_embedded_board(self):
        with patch("packages.infrastructure.jd_fetch.service.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.side_effect = [
                self._page_response(),
                self._api_response(),
            ]
            result = fetch_jd_from_url(_EMBED_URL)

        assert result.ok is True
        assert result.source == "ats_api"
        assert "Own the enterprise risk framework" in (result.jd_text or "")
        # Identity the page itself could never have supplied.
        assert result.title == "Quantitative Investment Risk Professional"
        assert result.company == "Careers at Acme"
        assert result.location == "New York, New York, United States"
        assert result.posted_at is not None and result.posted_at.year == 2026

    def test_token_found_in_html_escaped_embed_snippet(self):
        # CMS payloads carry the snippet escaped: src=\&#34;https://boards…&#34;
        escaped = _EMBED_PAGE.replace('"', "&#34;")
        with patch("packages.infrastructure.jd_fetch.service.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.side_effect = [
                self._page_response(escaped),
                self._api_response(),
            ]
            result = fetch_jd_from_url(_EMBED_URL)

        assert result.ok is True
        assert result.source == "ats_api"

    def test_url_without_gh_jid_never_calls_board_api(self):
        with patch("packages.infrastructure.jd_fetch.service.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = self._page_response(
                SAMPLE_HTML
            )
            result = fetch_jd_from_url("https://www.acme.com/careers/post")

        assert result.source == "worker_fetch"
        assert mock_client.return_value.__enter__.return_value.get.call_count == 1

    def test_token_survives_a_page_bigger_than_the_raw_cap(self):
        # CMS careers pages put the embed <script> last, past _MAX_RAW_BYTES on a
        # heavy page. The filler ahead of it scrapes into long clean prose that
        # passes validation, so a token scan bounded by _MAX_RAW_BYTES doesn't
        # just miss — it hands back the page shell as though it were the JD.
        assert len(_HEAVY_EMBED_PAGE) > _MAX_RAW_BYTES
        with patch("packages.infrastructure.jd_fetch.service.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.side_effect = [
                self._page_response(_HEAVY_EMBED_PAGE),
                self._api_response(),
            ]
            result = fetch_jd_from_url(_EMBED_URL)

        assert result.ok is True
        assert result.source == "ats_api"
        assert "Own the enterprise risk framework" in (result.jd_text or "")
        assert "Filler copy in the page shell" not in (result.jd_text or "")

    def test_gh_jid_page_without_embed_script_is_refused_not_scraped(self):
        # SAMPLE_HTML is a perfectly valid JD-looking page — that is the point.
        # A gh_jid says the posting renders from a client-side board, so the HTML
        # that came back is the careers-page chrome no matter how well it reads.
        with patch("packages.infrastructure.jd_fetch.service.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = self._page_response(
                SAMPLE_HTML
            )
            result = fetch_jd_from_url(_EMBED_URL)

        assert result.ok is False
        assert result.fetch_status == "shell"
        assert result.jd_text is None
        assert result.title is None
        # No token in the page → no board API call, and no Jina retry either.
        assert mock_client.return_value.__enter__.return_value.get.call_count == 1

    def test_job_pulled_from_board_is_refused_not_scraped(self):
        request = httpx.Request("GET", "https://boards-api.greenhouse.io/v1/boards/acmeboard/jobs/1")
        with patch("packages.infrastructure.jd_fetch.service.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.side_effect = [
                self._page_response(),
                httpx.HTTPStatusError("404", request=request, response=httpx.Response(404, request=request)),
            ]
            result = fetch_jd_from_url(_EMBED_URL)

        # Board 404s a job id that isn't on it — the unrendered page is all we
        # have, and it must not be passed off as a JD.
        assert result.ok is False
        assert result.source != "ats_api"
        assert result.title is None
        # Not "doa": a 404 also covers a mis-read token, and calling a live
        # posting dead is the more expensive mistake.
        assert result.fetch_status == "shell"
        # Refused outright — the page + board API, no third call to Jina.
        assert mock_client.return_value.__enter__.return_value.get.call_count == 2


# Unrendered-SPA chrome: no <script>/<style> wrapper, so strip_html keeps it and
# the CSS/JS token density trips is_shell_text (mirrors what _MAX_RAW_BYTES
# truncation does to a real page — an unclosed <script> leaks its body as text).
_SHELL_BODY = "var x = {a:1}; function f() { return {b:2}; } " * 200

_JOBPOSTING_LD = json.dumps(
    {
        "@type": "JobPosting",
        "title": "Junior Quantitative Specialist - Corporate &amp; Investment banking",
        "datePosted": "2026/07/15",
        "description": "<p>" + ("Model validation and stress testing work. " * 10) + "</p>",
        "hiringOrganization": {"@type": "Organization", "name": "Societe Generale"},
        "jobLocation": {
            "@type": "Place",
            "address": {"addressLocality": "New York", "addressRegion": "NY"},
        },
    }
)

_JSONLD_SHELL_PAGE = (
    "<html><head>"
    f'<script type="application/ld+json">{_JOBPOSTING_LD}</script>'
    f"</head><body>{_SHELL_BODY}</body></html>"
)

_SHELL_PAGE_NO_LD = f"<html><body>{_SHELL_BODY}</body></html>"


class TestJsonLdTier:
    """Schema.org JobPosting markup on JS-heavy careers pages — the scrape is
    chrome that fails the shell check while the full JD sits in ld+json
    (careers.societegenerale.com / careers.cobank.com, both real shell-refused
    imports)."""

    @staticmethod
    def _page(html):
        return httpx.Response(200, text=html, request=httpx.Request("GET", "https://x.com"))

    def test_shell_page_resolves_via_jsonld_with_identity(self):
        with patch("packages.infrastructure.jd_fetch.service.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = self._page(
                _JSONLD_SHELL_PAGE
            )
            result = fetch_jd_from_url("https://careers.example.com/en/job-offers/quant-1234")

        assert result.ok is True
        assert result.source == "jsonld"
        assert "Model validation and stress testing" in (result.jd_text or "")
        # Identity fields the scrape could never supply — title unescaped.
        assert result.title == "Junior Quantitative Specialist - Corporate & Investment banking"
        assert result.company == "Societe Generale"
        assert result.location == "New York, NY"
        assert result.posted_at is not None and result.posted_at.year == 2026
        # One page GET — no Jina, no board API.
        assert mock_client.return_value.__enter__.return_value.get.call_count == 1

    def test_jsonld_preferred_over_valid_scrape(self):
        # A server-rendered page with both readable prose AND JobPosting markup:
        # the markup wins (clean JD + identity vs page text with chrome).
        page = SAMPLE_HTML.replace(
            "</head>", f'<script type="application/ld+json">{_JOBPOSTING_LD}</script></head>'
        )
        with patch("packages.infrastructure.jd_fetch.service.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = self._page(page)
            result = fetch_jd_from_url("https://careers.example.com/job/1")

        assert result.source == "jsonld"
        assert result.company == "Societe Generale"

    def test_multiple_jobpostings_is_a_listing_page_and_not_used(self):
        # Two JobPosting objects = a listing page; picking one would attach the
        # wrong JD to the URL. Falls through to scrape judgement (shell here).
        two = f'<script type="application/ld+json">[{_JOBPOSTING_LD},{_JOBPOSTING_LD}]</script>'
        page = f"<html><head>{two}</head><body>{_SHELL_BODY}</body></html>"
        with patch("packages.infrastructure.jd_fetch.service.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = self._page(page)
            result = fetch_jd_from_url("https://careers.example.com/jobs")

        assert result.ok is False
        assert result.fetch_status == "shell"

    def test_malformed_jsonld_is_skipped_not_fatal(self):
        page = (
            '<html><head><script type="application/ld+json">{not json]</script>'
            f"</head><body>{SAMPLE_HTML}</body></html>"
        )
        with patch("packages.infrastructure.jd_fetch.service.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = self._page(page)
            result = fetch_jd_from_url("https://careers.example.com/job/1")

        assert result.ok is True
        assert result.source == "worker_fetch"

    def test_short_description_falls_through(self):
        posting = json.dumps({"@type": "JobPosting", "title": "X", "description": "too short"})
        page = (
            f'<html><head><script type="application/ld+json">{posting}</script>'
            f"</head><body>{SAMPLE_HTML}</body></html>"
        )
        with patch("packages.infrastructure.jd_fetch.service.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = self._page(page)
            result = fetch_jd_from_url("https://careers.example.com/job/1")

        assert result.ok is True
        assert result.source == "worker_fetch"

    def test_graph_container_and_type_list(self):
        from packages.infrastructure.jd_fetch.service import _jsonld_job_postings

        graph_page = (
            '<script type="application/ld+json">'
            + json.dumps(
                {
                    "@context": "https://schema.org",
                    "@graph": [
                        {"@type": "BreadcrumbList"},
                        {"@type": ["JobPosting", "Thing"], "title": "Quant"},
                    ],
                }
            )
            + "</script>"
        )
        postings = _jsonld_job_postings(graph_page)
        assert len(postings) == 1
        assert postings[0]["title"] == "Quant"

    def test_date_formats(self):
        from packages.infrastructure.jd_fetch.service import _parse_jsonld_date

        for raw in ("2026/07/15", "2026-07-15", "2026-07-03T15:54:00+0000", "2026-07-03T15:54:00Z"):
            parsed = _parse_jsonld_date(raw)
            assert parsed is not None and parsed.tzinfo is not None, raw
        assert _parse_jsonld_date("soon") is None
        assert _parse_jsonld_date(None) is None


class TestAntiBotJinaFallback:
    """A 403 is an anti-bot wall, not a page judgement — Jina's renderer gets
    through where the direct fetch can't (real case: jobs.fidelity.com behind
    Cloudflare)."""

    def test_403_falls_back_to_jina(self):
        request = httpx.Request("GET", "https://jobs.example.com/job/1")
        with patch("packages.infrastructure.jd_fetch.service.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.side_effect = [
                httpx.HTTPStatusError(
                    "403", request=request, response=httpx.Response(403, request=request)
                ),
                httpx.Response(
                    200,
                    text="Job Description: " + ("real responsibilities here. " * 20),
                    request=httpx.Request("GET", "https://r.jina.ai/x"),
                ),
            ]
            result = fetch_jd_from_url("https://jobs.example.com/job/1")

        assert result.ok is True
        assert result.source == "worker_fetch"
        assert "real responsibilities" in (result.jd_text or "")

    def test_403_with_failed_jina_stays_failed_403(self):
        request = httpx.Request("GET", "https://jobs.example.com/job/1")
        with patch("packages.infrastructure.jd_fetch.service.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.side_effect = [
                httpx.HTTPStatusError(
                    "403", request=request, response=httpx.Response(403, request=request)
                ),
                httpx.Response(200, text="hi", request=httpx.Request("GET", "https://r.jina.ai/x")),
            ]
            result = fetch_jd_from_url("https://jobs.example.com/job/1")

        assert result.ok is False
        assert result.fetch_status == "failed"
        assert result.http_status == 403

    def test_404_does_not_try_jina(self):
        # 404/410 mean the posting is gone — rendering harder won't revive it.
        request = httpx.Request("GET", "https://jobs.example.com/gone")
        with patch("packages.infrastructure.jd_fetch.service.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.side_effect = [
                httpx.HTTPStatusError(
                    "404", request=request, response=httpx.Response(404, request=request)
                ),
            ]
            result = fetch_jd_from_url("https://jobs.example.com/gone")

        assert result.fetch_status == "doa"
        assert mock_client.return_value.__enter__.return_value.get.call_count == 1

    def test_shell_without_jsonld_is_refused_without_jina(self):
        # A density-shell page with no JobPosting markup is a listing page or a
        # pulled posting in every observed case; rendering it via Jina would
        # produce prose that validates but isn't this job's JD (false accept).
        with patch("packages.infrastructure.jd_fetch.service.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = httpx.Response(
                200, text=_SHELL_PAGE_NO_LD, request=httpx.Request("GET", "https://x.com")
            )
            result = fetch_jd_from_url("https://careers.example.com/careers")

        assert result.ok is False
        assert result.fetch_status == "shell"
        assert mock_client.return_value.__enter__.return_value.get.call_count == 1


_CLOUDFLARE_INTERSTITIAL = (
    "Title: Just a moment...\n\n"
    "URL Source: https://www.indeed.com/viewjob?jk=cb4d4c846374e999\n\n"
    "Markdown Content:\n"
    + "Enable JavaScript and cookies to continue. " * 25
)


class TestAntiBotChallengeDetection:
    """A challenge page fetched *successfully* by the renderer. It is long
    enough and clean enough to pass every other check in _validate_jd_text, so
    without a marker for it the interstitial gets stored as a posting's JD.
    Real case: an indeed.com import returned "Just a moment..." — measured at
    1,509 chars, which validated clean."""

    def test_interstitial_is_rejected_by_validation(self):
        from packages.infrastructure.jd_fetch.service import _validate_jd_text

        result = _validate_jd_text(_CLOUDFLARE_INTERSTITIAL)
        assert result.ok is False
        assert result.fetch_status == "shell"

    def test_403_with_a_challenge_from_jina_stays_failed(self):
        # The 403 -> Jina hop must not turn an anti-bot wall into a stored JD.
        request = httpx.Request("GET", "https://jobs.example.com/job/1")
        with patch("packages.infrastructure.jd_fetch.service.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.side_effect = [
                httpx.HTTPStatusError(
                    "403", request=request, response=httpx.Response(403, request=request)
                ),
                httpx.Response(
                    200,
                    text=_CLOUDFLARE_INTERSTITIAL,
                    request=httpx.Request("GET", "https://r.jina.ai/x"),
                ),
            ]
            result = fetch_jd_from_url("https://jobs.example.com/job/1")

        assert result.ok is False
        assert result.jd_text is None
        assert result.http_status == 403

    def test_marker_deep_in_a_real_jd_is_not_a_challenge(self):
        # Both bounds matter: the phrase must be in the head *and* the document
        # short. A long posting that uses the words mid-body is a posting.
        from packages.infrastructure.jd_fetch.service import is_antibot_challenge

        jd = ("We move fast here. " * 40) + "Please wait, just a moment — verify you are human? " \
             + ("No: we value real conversation with candidates. " * 40)
        assert is_antibot_challenge(jd) is False

    def test_long_challenge_page_is_not_flagged(self):
        from packages.infrastructure.jd_fetch.service import is_antibot_challenge

        assert is_antibot_challenge("Just a moment..." + "x" * 6000) is False

    def test_empty_text_is_not_flagged(self):
        from packages.infrastructure.jd_fetch.service import is_antibot_challenge

        assert is_antibot_challenge("") is False


class TestArtifactCache:
    def test_save_and_resolve_from_artifact(self, tmp_path: Path):
        url = "https://boards.greenhouse.io/acme/jobs/123"
        jd_text = "Senior Engineer role. " + ("Details here. " * 40)
        save_fetched_jd_artifact(
            artifact_dir=tmp_path,
            url=url,
            raw_content=jd_text,
            content_type="text/plain",
        )

        with patch("packages.infrastructure.jd_fetch.service.fetch_jd_from_url") as mock_fetch:
            result = resolve_jd(url, "greenhouse", tmp_path)

        mock_fetch.assert_not_called()
        assert result.ok is True
        assert result.source == "artifact"

    def test_resolve_falls_back_to_fetch_when_no_artifact(self, tmp_path: Path):
        url = "https://example.com/job/2"
        with patch("packages.infrastructure.jd_fetch.service.fetch_jd_from_url") as mock_fetch:
            mock_fetch.return_value.ok = True
            mock_fetch.return_value.jd_text = "x" * MIN_JD_TEXT_LEN
            mock_fetch.return_value.jd_hash = compute_jd_hash("x" * MIN_JD_TEXT_LEN)
            mock_fetch.return_value.error = None
            mock_fetch.return_value.fetch_status = "success"
            mock_fetch.return_value.source = "worker_fetch"

            result = resolve_jd(url, "html_fallback", tmp_path)

        mock_fetch.assert_called_once_with(url)
        assert result.ok is True
        assert result.source == "worker_fetch"


def _make_manifest(pool_path: Path, count: int = 1) -> DiscoveryManifest:
    return DiscoveryManifest(
        invocation_id="ainv_test",
        status="completed",
        stop_reason="done",
        candidate_count=count,
        sources_tried=["greenhouse"],
        artifact_paths={"candidate_pool": str(pool_path)},
    )


class TestPersistDiscoveredJobs:
    def test_reportable_on_successful_fetch(self, tmp_path: Path):
        pool = tmp_path / "candidate_pool.jsonl"
        url = "https://example.com/job/new"
        pool.write_text(
            json.dumps(
                {
                    "url": url,
                    "title": "Analyst",
                    "company": "Acme",
                    "source_type": "greenhouse",
                }
            )
            + "\n"
        )
        manifest = _make_manifest(pool)

        mock_job = MagicMock()
        mock_job.id = "job-001"
        mock_job_repo = MagicMock()
        mock_job_repo.get_by_canonical_url.return_value = None
        mock_job_repo.create.return_value = mock_job

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        mock_dead_repo = MagicMock()
        mock_dead_repo.is_dead.return_value = False

        ok_result = MagicMock()
        ok_result.ok = True
        ok_result.jd_text = "Role description. " * 30
        ok_result.jd_hash = compute_jd_hash(ok_result.jd_text)
        ok_result.error = None
        ok_result.source = "worker_fetch"
        ok_result.fetch_status = "success"

        with patch("apps.worker.tasks.search_run.get_session", return_value=mock_session), patch(
            "apps.worker.tasks.search_run.JobRepository", return_value=mock_job_repo
        ), patch(
            "apps.worker.tasks.search_run.DeadUrlRepository", return_value=mock_dead_repo
        ), patch("apps.worker.tasks.search_run.resolve_jd", return_value=ok_result):
            from apps.worker.tasks.search_run import _persist_discovered_jobs

            stats = _persist_discovered_jobs(manifest, "run_1", "task_1")

        assert stats["jobs_ingested"] == 1
        assert stats["jobs_reportable"] == 1
        assert stats["jobs_fetch_failed"] == 0
        _, kwargs = mock_job_repo.create.call_args
        assert kwargs["status"] == "reportable"
        assert kwargs["jd_text"] == ok_result.jd_text

    def test_discovered_with_fetch_error_on_failure(self, tmp_path: Path):
        pool = tmp_path / "candidate_pool.jsonl"
        url = "https://example.com/job/fail"
        pool.write_text(
            json.dumps(
                {
                    "url": url,
                    "title": "Analyst",
                    "company": "Acme",
                    "source_type": "greenhouse",
                }
            )
            + "\n"
        )
        manifest = _make_manifest(pool)

        mock_job = MagicMock()
        mock_job.id = "job-002"
        mock_job_repo = MagicMock()
        mock_job_repo.get_by_canonical_url.return_value = None
        mock_job_repo.create.return_value = mock_job

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        mock_dead_repo = MagicMock()
        mock_dead_repo.is_dead.return_value = False

        fail_result = MagicMock()
        fail_result.ok = False
        fail_result.jd_text = None
        fail_result.jd_hash = None
        fail_result.error = "HTTP 404 fetching url"
        fail_result.source = "worker_fetch"
        fail_result.fetch_status = "failed"

        with patch("apps.worker.tasks.search_run.get_session", return_value=mock_session), patch(
            "apps.worker.tasks.search_run.JobRepository", return_value=mock_job_repo
        ), patch(
            "apps.worker.tasks.search_run.DeadUrlRepository", return_value=mock_dead_repo
        ), patch("apps.worker.tasks.search_run.resolve_jd", return_value=fail_result):
            from apps.worker.tasks.search_run import _persist_discovered_jobs

            stats = _persist_discovered_jobs(manifest, "run_1", "task_1")

        assert stats["jobs_fetch_failed"] == 1
        assert stats["jobs_reportable"] == 0
        _, kwargs = mock_job_repo.create.call_args
        assert kwargs["status"] == "discovered"
        assert kwargs["raw_payload_json"]["fetch_error"] == "HTTP 404 fetching url"

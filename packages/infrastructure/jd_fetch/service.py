"""
JD fetch service — shared by worker ingest and career_fetch_source wrapper.

Resolution order (resolve_jd):
  1. Artifact cache at {artifact_dir}/fetched_jds/{url_hash}.txt (Phase B)
  2. Worker deterministic HTTP fetch (Phase A fallback), which itself prefers
     the ATS's structured JSON API (see _fetch_via_ats_api) over scraping the
     page when the URL matches a known board — cleaner text, no page chrome,
     and no dependency on the agent correctly self-reporting source_type.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import httpx

MIN_JD_TEXT_LEN = 200
_MAX_RAW_BYTES = 200_000
_MAX_JD_TEXT_CHARS = 50_000
# CMS-rendered careers pages put the Greenhouse embed <script> at the very
# bottom of the document, which on a heavy page lands past _MAX_RAW_BYTES (a
# real one: 236,830 chars total, token at 236,743). _MAX_RAW_BYTES bounds the
# HTML→text normalization, so it can't be raised for that; the token scan is a
# regex over the response and affords a far wider window at negligible cost.
_MAX_EMBED_SCAN_CHARS = 2_000_000

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; career-intelligence/0.1; +research-bot)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

JdSource = Literal["artifact", "worker_fetch", "ats_api", "jsonld"]


@dataclass(frozen=True)
class JdFetchResult:
    ok: bool
    jd_text: str | None
    jd_hash: str | None
    error: str | None
    source: JdSource | None
    fetch_status: str  # "success" | "failed" | "too_short" | "doa"
    http_status: int | None = None
    # Employer posting date — only the ATS-API tier can supply it; the scrape /
    # Jina tiers leave it None. UTC-aware.
    posted_at: datetime | None = None
    # Posting identity as the ATS itself reports it. Only the ATS-API tiers fill
    # these; a scrape leaves them None. Callers use them to avoid guessing a
    # title/company out of the URL — see job_ingest_service.ingest_from_url,
    # which refuses the import outright rather than write a URL-guessed row.
    title: str | None = None
    company: str | None = None
    location: str | None = None


def compute_url_hash(url: str) -> str:
    """Stable cache key for a job posting URL."""
    return hashlib.md5(url.encode("utf-8")).hexdigest()[:16]


def url_hash_for_cache(url: str) -> str:
    """Alias for compute_url_hash — used in artifact paths."""
    return compute_url_hash(url)


def compute_jd_hash(jd_text: str) -> str:
    """Match job_report_service cache key format."""
    return hashlib.md5(jd_text.encode("utf-8")).hexdigest()[:16]


def strip_html(html: str) -> str:
    """Minimal HTML stripping — port from career-openclaw fetcher."""
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&#\d+;", "", text)
    text = re.sub(r"\s{3,}", "\n\n", text)
    return text.strip()


def _normalize_fetched_content(raw: str, content_type: str = "") -> str:
    if "html" in content_type.lower() or "<" in raw[:500]:
        return strip_html(raw)
    return raw.strip()


_CLOSED_POSTING_MARKERS = (
    "no longer accepting applications",
    "no longer accepting application",
    "position has been filled",
    "this job is no longer available",
    "this position is no longer available",
    "job posting is closed",
    "posting has expired",
    "applications are closed",
)


def _is_closed_posting(text: str) -> bool:
    """Conservative closed-posting (DOA) detection.

    Only fires when the fetched text is short enough to be a status page rather
    than a full JD — a real JD that merely mentions one of these phrases in its
    body must not be misclassified as dead. Long text (a real posting) is never
    flagged, which biases toward keeping a live posting over dropping one.
    """
    if len(text) > 1000:
        return False
    low = text.lower()
    return any(marker in low for marker in _CLOSED_POSTING_MARKERS)


_SHELL_STUB_MARKERS = (
    "enable javascript",
    "please enable js",
    "javascript is required",
    "loading...",
    "please wait",
)

# Real JDs measure < 2 CSS/JS markup tokens per 1000 chars; unrendered SPA
# shells measure 30+. The threshold sits in the wide empty gap between them
# (calibrated on production data: real JDs 0.0-1.8, shells 30.6-37.2), so a
# genuine posting is never dropped as a shell.
_SHELL_DENSITY_THRESHOLD = 10.0


def is_shell_text(text: str) -> bool:
    """High-confidence page-shell detection: the fetched text is mostly CSS/JS
    chrome (an unrendered single-page-app), not job-description prose. Used so a
    50KB blob of stylesheet isn't accepted as a valid JD just for being long.
    """
    if not text:
        return False
    low = text.lower()
    if len(text) < 2000 and any(m in low for m in _SHELL_STUB_MARKERS):
        return True
    tokens = (
        text.count("{")
        + text.count("}")
        + text.count(";")
        + low.count("function")
        + low.count("px;")
        + low.count("rgba")
        + low.count("@media")
        + low.count("var ")
        + low.count("</")
        + low.count("/>")
    )
    return tokens / (len(text) / 1000.0) > _SHELL_DENSITY_THRESHOLD


def _validate_jd_text(jd_text: str) -> JdFetchResult:
    if len(jd_text) < MIN_JD_TEXT_LEN:
        return JdFetchResult(
            ok=False,
            jd_text=None,
            jd_hash=None,
            error=f"JD text too short ({len(jd_text)} chars, min {MIN_JD_TEXT_LEN})",
            source=None,
            fetch_status="too_short",
        )
    if is_shell_text(jd_text):
        return JdFetchResult(
            ok=False,
            jd_text=None,
            jd_hash=None,
            error="Fetched text looks like a page shell (CSS/JS), not a JD",
            source=None,
            fetch_status="shell",
        )
    capped = jd_text[:_MAX_JD_TEXT_CHARS]
    jd_hash = compute_jd_hash(capped)
    return JdFetchResult(
        ok=True,
        jd_text=capped,
        jd_hash=jd_hash,
        error=None,
        source=None,
        fetch_status="success",
    )


def _artifact_paths(artifact_dir: Path, url: str) -> tuple[Path, Path]:
    url_hash = url_hash_for_cache(url)
    cache_dir = artifact_dir / "fetched_jds"
    return cache_dir / f"{url_hash}.txt", cache_dir / f"{url_hash}.meta.json"


def _read_jd_artifact(artifact_dir: Path, url: str) -> JdFetchResult | None:
    text_path, _meta_path = _artifact_paths(artifact_dir, url)
    if not text_path.exists():
        return None
    try:
        jd_text = text_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        return JdFetchResult(
            ok=False,
            jd_text=None,
            jd_hash=None,
            error=f"Failed to read JD artifact: {exc}",
            source="artifact",
            fetch_status="failed",
        )
    result = _validate_jd_text(jd_text)
    if result.ok:
        return JdFetchResult(
            ok=True,
            jd_text=result.jd_text,
            jd_hash=result.jd_hash,
            error=None,
            source="artifact",
            fetch_status="success",
        )
    return JdFetchResult(
        ok=False,
        jd_text=None,
        jd_hash=None,
        error=result.error,
        source="artifact",
        fetch_status=result.fetch_status,
    )


def save_fetched_jd_artifact(
    *,
    artifact_dir: Path,
    url: str,
    raw_content: str,
    content_type: str = "",
) -> tuple[Path, str, str]:
    """
    Strip HTML, save to fetched_jds cache, return (text_path, jd_text, jd_hash).

    Raises ValueError if normalized text is too short.
    """
    jd_text = _normalize_fetched_content(raw_content, content_type)
    validated = _validate_jd_text(jd_text)
    if not validated.ok:
        raise ValueError(validated.error or "JD text invalid")

    assert validated.jd_text is not None
    assert validated.jd_hash is not None

    text_path, meta_path = _artifact_paths(artifact_dir, url)
    text_path.parent.mkdir(parents=True, exist_ok=True)
    text_path.write_text(validated.jd_text, encoding="utf-8")
    meta_path.write_text(
        json.dumps(
            {
                "url": url,
                "url_hash": url_hash_for_cache(url),
                "jd_hash": validated.jd_hash,
                "content_length": len(validated.jd_text),
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return text_path, validated.jd_text, validated.jd_hash


def _fetch_via_jina(url: str, *, timeout: float = 15.0) -> JdFetchResult:
    """Fallback: use Jina Reader to render JS-heavy pages (Workday, etc.)."""
    jina_url = f"https://r.jina.ai/{url}"
    try:
        with httpx.Client(
            headers={"Accept": "text/plain", **_HEADERS},
            follow_redirects=True,
            timeout=timeout,
        ) as client:
            response = client.get(jina_url)
            response.raise_for_status()
        jd_text = response.text[:_MAX_JD_TEXT_CHARS].strip()
        validated = _validate_jd_text(jd_text)
        return JdFetchResult(
            ok=validated.ok,
            jd_text=validated.jd_text,
            jd_hash=validated.jd_hash,
            error=validated.error,
            source="worker_fetch",
            fetch_status=validated.fetch_status,
        )
    except Exception:
        return JdFetchResult(
            ok=False, jd_text=None, jd_hash=None,
            error=f"Jina fallback failed for {url}",
            source="worker_fetch", fetch_status="failed",
        )


def _fetch_via_ats_api(url: str, *, timeout: float = 10.0) -> JdFetchResult | None:
    """
    Try resolving a job posting via its ATS's own structured JSON API instead
    of scraping the page. Detection is URL-pattern based (extract_board_info),
    not caller-supplied source_type — an agent that misclassifies a URL still
    gets routed correctly, and one that's right doesn't need to be trusted.

    Returns None (caller falls back to scraping) whenever the shortcut isn't
    available: URL doesn't match a known ATS board, the board API call fails,
    or this specific job isn't in the board's current listing (e.g. filled or
    pulled since the URL was discovered). Never raises.
    """
    from packages.domain.agent_jobs.ats_providers import (
        build_api_url,
        extract_board_info,
        parse_board_response,
    )
    from packages.domain.agent_jobs.url_normalize import normalize_job_url

    board_info = extract_board_info(url)
    if not board_info:
        return None
    provider, token = board_info
    api_url = build_api_url(provider, token)
    if not api_url:
        return None

    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(api_url)
            response.raise_for_status()
        board_jobs = parse_board_response(provider, response.json())
    except Exception:
        return None

    match = next(
        (bj for bj in board_jobs if normalize_job_url(bj.url) == normalize_job_url(url)),
        None,
    )
    if match is None or not match.jd_plain:
        return None

    validated = _validate_jd_text(match.jd_plain)
    if not validated.ok:
        return None

    return JdFetchResult(
        ok=True,
        jd_text=validated.jd_text,
        jd_hash=validated.jd_hash,
        error=None,
        source="ats_api",
        fetch_status="success",
        posted_at=match.posted_at,
        title=(match.title or "").strip() or None,
        company=match.company or None,
        location=match.location,
    )


# Schema.org structured data — careers sites embed the posting for search
# engines even when the visible page renders client-side. On a JS-heavy page
# the JD is often *only* here: the scraped text is 98K chars of chrome that
# fails the shell check while a complete JobPosting sits in this block
# (careers.societegenerale.com, careers.cobank.com — both real shell-refused
# imports recovered by this tier).
_JSONLD_SCRIPT_RE = re.compile(
    r"<script[^>]*type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
    re.DOTALL | re.IGNORECASE,
)


def _parse_jsonld_date(raw: object) -> datetime | None:
    """datePosted → UTC-aware datetime. Sites vary: ISO ("2026-07-03T15:54:00
    +0000"), date-only ("2026-07-15"), and slash-dates ("2026/07/15")."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip().replace("/", "-").replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _is_jobposting_type(type_field: object) -> bool:
    if isinstance(type_field, str):
        return type_field == "JobPosting"
    if isinstance(type_field, list):
        return "JobPosting" in type_field
    return False


def _jsonld_job_postings(page_html: str) -> list[dict]:
    """Every JobPosting object in the page's ld+json blocks (top-level object,
    top-level array, or @graph container). Malformed JSON is skipped."""
    postings: list[dict] = []
    for match in _JSONLD_SCRIPT_RE.finditer(page_html):
        try:
            data = json.loads(match.group(1).strip())
        except ValueError:
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            graph = item.get("@graph")
            candidates = graph if isinstance(graph, list) else [item]
            for candidate in candidates:
                if isinstance(candidate, dict) and _is_jobposting_type(
                    candidate.get("@type")
                ):
                    postings.append(candidate)
    return postings


def _jsonld_location(posting: dict) -> str | None:
    """jobLocation → "City, Region" best effort. jobLocation may be an object
    or a list of objects; address fields are all optional."""
    loc = posting.get("jobLocation")
    if isinstance(loc, list):
        loc = loc[0] if loc else None
    if not isinstance(loc, dict):
        return None
    address = loc.get("address")
    if not isinstance(address, dict):
        return None
    parts = [
        str(address.get(key)).strip()
        for key in ("addressLocality", "addressRegion")
        if isinstance(address.get(key), str) and address.get(key).strip()
    ]
    return ", ".join(parts) or None


def _fetch_via_jsonld(page_html: str) -> JdFetchResult | None:
    """Resolve a posting from the page's schema.org JobPosting markup.

    Only fires when the page carries exactly ONE JobPosting — a detail page.
    Multiple postings mean a listing page, where picking one would attach the
    wrong JD to the URL. Returns None whenever the tier doesn't apply (no
    markup, listing page, no/short description) and the caller falls through
    to scrape validation. Never raises.
    """
    from packages.domain.agent_jobs.ats_providers import _strip_html as ats_strip_html

    postings = _jsonld_job_postings(page_html)
    if len(postings) != 1:
        return None
    posting = postings[0]

    description = posting.get("description")
    if not isinstance(description, str):
        return None
    validated = _validate_jd_text(ats_strip_html(description))
    if not validated.ok:
        return None

    import html as _html

    org = posting.get("hiringOrganization")
    company = org.get("name") if isinstance(org, dict) else org
    title = posting.get("title")
    # Titles arrive HTML-escaped ("Corporate &amp; Investment banking").
    title = _html.unescape(title).strip() if isinstance(title, str) else None
    company = _html.unescape(company).strip() if isinstance(company, str) else None

    return JdFetchResult(
        ok=True,
        jd_text=validated.jd_text,
        jd_hash=validated.jd_hash,
        error=None,
        source="jsonld",
        fetch_status="success",
        posted_at=_parse_jsonld_date(posting.get("datePosted")),
        title=title or None,
        company=company or None,
        location=_jsonld_location(posting),
    )


# A company careers page that mounts a Greenhouse board client-side ships this
# script tag; `for=` is the board token, which appears nowhere in the job URL.
_GREENHOUSE_EMBED_TOKEN_RE = re.compile(
    r"greenhouse\.io/embed/job_board/js\?for=([A-Za-z0-9_-]+)", re.I
)


def _greenhouse_embed_job_id(url: str) -> str | None:
    """The Greenhouse job id a careers URL carries in `?gh_jid=`, if any.

    Its presence is the marker that the page renders its posting from a
    client-side board — the JD is not in the HTML that comes back.
    """
    from urllib.parse import parse_qs, urlsplit

    job_ids = parse_qs(urlsplit(url).query).get("gh_jid") or []
    job_id = job_ids[0].strip() if job_ids else ""
    return job_id if job_id.isdigit() else None


def _fetch_via_greenhouse_embed(
    url: str, page_html: str, *, timeout: float = 10.0
) -> JdFetchResult | None:
    """
    Resolve a Greenhouse posting embedded in a company's own careers page.

    These URLs carry the job id in `?gh_jid=` on the employer's domain
    (www.kkr.com/careers/…?gh_jid=6107228004) and render the JD client-side, so
    extract_board_info() can't see a board and scraping the page yields only
    chrome. The board token lives in the page's embed <script>; with it, the
    posting resolves through Greenhouse's own single-job endpoint.

    Unlike _fetch_via_ats_api this doesn't re-check that the returned job's URL
    matches: the (token, job id) pair is the identity proof — Greenhouse 404s a
    job id that isn't on that board. Returns None whenever the shortcut isn't
    available (no gh_jid, no token in the page, API error, posting pulled from
    the board, unusable content) and the caller falls back to the scrape.
    Never raises.
    """
    from packages.domain.agent_jobs.ats_providers import parse_board_response

    job_id = _greenhouse_embed_job_id(url)
    if job_id is None:
        return None

    token_match = _GREENHOUSE_EMBED_TOKEN_RE.search(page_html)
    if not token_match:
        # The embed snippet is often HTML-escaped inside a CMS payload
        # (src=\&#34;https://boards.greenhouse.io/embed/…&#34;).
        import html as _html

        token_match = _GREENHOUSE_EMBED_TOKEN_RE.search(_html.unescape(page_html))
    if not token_match:
        return None
    token = token_match.group(1).lower()

    api_url = (
        f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{job_id}?content=true"
    )
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(api_url)
            response.raise_for_status()
        payload = response.json()
    except Exception:
        return None

    # The single-job payload is one element of the board listing's "jobs" array,
    # so the board parser (HTML → text, posted_at, location) applies unchanged.
    board_jobs = parse_board_response("greenhouse", {"jobs": [payload]})
    if not board_jobs or not board_jobs[0].jd_plain:
        return None
    match = board_jobs[0]

    validated = _validate_jd_text(match.jd_plain)
    if not validated.ok:
        return None

    return JdFetchResult(
        ok=True,
        jd_text=validated.jd_text,
        jd_hash=validated.jd_hash,
        error=None,
        source="ats_api",
        fetch_status="success",
        posted_at=match.posted_at,
        title=(match.title or "").strip() or None,
        company=match.company or None,
        location=match.location,
    )


def fetch_jd_from_url(url: str, *, timeout: float = 15.0) -> JdFetchResult:
    """Deterministic HTTP fetch + normalize (worker fallback)."""
    if not url.startswith(("http://", "https://")):
        return JdFetchResult(
            ok=False,
            jd_text=None,
            jd_hash=None,
            error=f"Invalid URL: {url!r}",
            source="worker_fetch",
            fetch_status="failed",
        )

    ats_result = _fetch_via_ats_api(url, timeout=min(timeout, 10.0))
    if ats_result is not None:
        return ats_result

    try:
        with httpx.Client(
            headers=_HEADERS,
            follow_redirects=True,
            timeout=timeout,
        ) as client:
            response = client.get(url)
            response.raise_for_status()
        page_text = response.text
        raw = page_text[:_MAX_RAW_BYTES]
        embed_scan = page_text[:_MAX_EMBED_SCAN_CHARS]
        content_type = response.headers.get("content-type", "")
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        # 403 is an anti-bot wall (Cloudflare "Just a moment..."), not a page
        # judgement — the posting is usually alive and Jina's renderer gets
        # through where the direct fetch can't (real case: jobs.fidelity.com).
        if code == 403:
            jina_result = _fetch_via_jina(url, timeout=max(timeout, 30.0))
            if jina_result.ok:
                return jina_result
        # 404/410 = the posting is gone (DOA). Other statuses (403 anti-bot,
        # 5xx, etc.) are fetch failures, not proof the job is dead — keep them
        # as "failed" so the job is still recorded and retried.
        return JdFetchResult(
            ok=False,
            jd_text=None,
            jd_hash=None,
            error=f"HTTP {code} fetching {url}",
            source="worker_fetch",
            fetch_status="doa" if code in (404, 410) else "failed",
            http_status=code,
        )
    except httpx.TimeoutException:
        return JdFetchResult(
            ok=False,
            jd_text=None,
            jd_hash=None,
            error=f"Timeout fetching {url}",
            source="worker_fetch",
            fetch_status="failed",
        )
    except Exception as exc:
        return JdFetchResult(
            ok=False,
            jd_text=None,
            jd_hash=None,
            error=f"{type(exc).__name__}: {exc}",
            source="worker_fetch",
            fetch_status="failed",
        )

    jd_text = _normalize_fetched_content(raw, content_type)

    if _is_closed_posting(jd_text):
        return JdFetchResult(
            ok=False,
            jd_text=None,
            jd_hash=None,
            error="Posting appears closed (page loaded but says no longer available)",
            source="worker_fetch",
            fetch_status="doa",
            http_status=200,
        )

    # Preferred over the scrape even when the scrape passed validation: on a
    # page that mounts the board client-side, what we just scraped is the
    # careers-page chrome, and the board API is the only source of the real JD
    # and title. Costs one JSON GET, and only on pages carrying a gh_jid.
    # Scanned over the wide window, not `raw` — see _MAX_EMBED_SCAN_CHARS.
    embedded = _fetch_via_greenhouse_embed(url, embed_scan, timeout=min(timeout, 10.0))
    if embedded is not None:
        return embedded

    # Schema.org JobPosting markup, before judging the scraped text: on a
    # JS-heavy detail page the scrape is chrome that fails the shell check
    # while the complete JD sits in the ld+json block — plus the ATS-reported
    # title/company/posted_at the scrape can never give. Zero extra requests.
    jsonld = _fetch_via_jsonld(embed_scan)
    if jsonld is not None:
        return jsonld

    # The board tier was the only way to read this posting and it didn't land
    # (no token in the page, API error, job pulled from the board). Whatever the
    # scrape holds, it is not this job's JD — it's the careers-page chrome. Some
    # of those pages carry a sidebar listing of other openings, which reads
    # enough like prose to pass is_shell_text(): a heavy one produced 7.5K chars
    # of navigation that validated clean, and the caller wrote it to a
    # `reportable` row with a page-title guess for a title. Refuse instead. A
    # false refusal costs the user a paste; a false accept is a silently wrong
    # row with nothing to flag it. No Jina retry here for the same reason: it
    # renders the board *listing* when the posting is gone, which validates as
    # prose and would be accepted as this job's JD.
    if _greenhouse_embed_job_id(url) is not None:
        return JdFetchResult(
            ok=False,
            jd_text=None,
            jd_hash=None,
            error=(
                "Posting is rendered from an embedded job board that could not "
                "be resolved; the fetched page is not the job description"
            ),
            source="worker_fetch",
            # Deliberately not "doa" — a board 404 usually means the posting was
            # pulled, but it also covers a mis-read token, and calling a live job
            # dead is the more expensive mistake.
            fetch_status="shell",
            http_status=200,
        )

    validated = _validate_jd_text(jd_text)

    # Jina only on "too_short" — deliberately NOT on "shell". A density-shell
    # page with no JobPosting markup is, in every observed case, either a
    # listing page or a pulled posting; rendering it produces prose that
    # validates but isn't this job's JD (a false accept, the expensive
    # mistake). The real shell-refused detail pages are recovered by the
    # JSON-LD tier above without any extra request.
    if not validated.ok and validated.fetch_status == "too_short":
        jina_result = _fetch_via_jina(url, timeout=max(timeout, 30.0))
        if jina_result.ok:
            return jina_result

    return JdFetchResult(
        ok=validated.ok,
        jd_text=validated.jd_text,
        jd_hash=validated.jd_hash,
        error=validated.error,
        source="worker_fetch",
        fetch_status=validated.fetch_status,
    )


def resolve_jd(url: str, source_type: str, artifact_dir: Path) -> JdFetchResult:  # noqa: ARG001
    """
    Resolve JD text for a candidate URL.

    Prefers artifact cache (career_fetch_source), falls back to worker fetch
    (which itself tries the ATS structured API before scraping — see
    _fetch_via_ats_api). source_type is unused: the ATS routing decision is
    made from the URL itself, not from this caller-supplied hint.
    """
    _ = source_type
    cached = _read_jd_artifact(artifact_dir, url)
    if cached is not None:
        if cached.ok:
            return cached
        # Invalid/stale cache — fall through to worker fetch

    fetched = fetch_jd_from_url(url)
    return fetched

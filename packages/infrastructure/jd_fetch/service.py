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

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; career-intelligence/0.1; +research-bot)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

JdSource = Literal["artifact", "worker_fetch", "ats_api"]


@dataclass(frozen=True)
class JdFetchResult:
    ok: bool
    jd_text: str | None
    jd_hash: str | None
    error: str | None
    source: JdSource | None
    fetch_status: str  # "success" | "failed" | "too_short" | "doa"
    http_status: int | None = None


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
        raw = response.text[:_MAX_RAW_BYTES]
        content_type = response.headers.get("content-type", "")
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
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

    validated = _validate_jd_text(jd_text)

    if not validated.ok and validated.fetch_status == "too_short":
        jina_result = _fetch_via_jina(url, timeout=timeout)
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

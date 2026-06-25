"""
JD fetch service — shared by worker ingest and career_fetch_source wrapper.

Resolution order (resolve_jd):
  1. Artifact cache at {artifact_dir}/fetched_jds/{url_hash}.txt (Phase B)
  2. Worker deterministic HTTP fetch (Phase A fallback)
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

JdSource = Literal["artifact", "worker_fetch"]


@dataclass(frozen=True)
class JdFetchResult:
    ok: bool
    jd_text: str | None
    jd_hash: str | None
    error: str | None
    source: JdSource | None
    fetch_status: str  # "success" | "failed" | "too_short"


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
        return JdFetchResult(
            ok=False,
            jd_text=None,
            jd_hash=None,
            error=f"HTTP {exc.response.status_code} fetching {url}",
            source="worker_fetch",
            fetch_status="failed",
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
    validated = _validate_jd_text(jd_text)
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

    Prefers artifact cache (career_fetch_source), falls back to worker fetch.
    source_type is reserved for future ATS-specific connectors.
    """
    _ = source_type
    cached = _read_jd_artifact(artifact_dir, url)
    if cached is not None:
        if cached.ok:
            return cached
        # Invalid/stale cache — fall through to worker fetch

    fetched = fetch_jd_from_url(url)
    return fetched

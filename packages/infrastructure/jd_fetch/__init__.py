"""JD fetch and artifact cache for discovery ingest."""

from packages.infrastructure.jd_fetch.service import (
    JdFetchResult,
    MIN_JD_TEXT_LEN,
    compute_jd_hash,
    compute_url_hash,
    fetch_jd_from_url,
    resolve_jd,
    save_fetched_jd_artifact,
    strip_html,
    url_hash_for_cache,
)

__all__ = [
    "JdFetchResult",
    "MIN_JD_TEXT_LEN",
    "compute_jd_hash",
    "compute_url_hash",
    "fetch_jd_from_url",
    "resolve_jd",
    "save_fetched_jd_artifact",
    "strip_html",
    "url_hash_for_cache",
]

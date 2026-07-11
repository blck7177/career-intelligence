"""
Per-domain outbound-fetch pacing for career_fetch_source.

career_fetch_source hits ATS hosts we have no relationship with (greenhouse,
lever, ashby, workday). We are not a paying API client of theirs — hammering
the same host from concurrent agent invocations risks IP-based blocking,
which would degrade job data for every workspace, not just the one that
triggered it.

This enforces a minimum interval between fetches to the same hostname,
regardless of how many agent invocations are running concurrently. It is
*not* per-workspace: the target server doesn't care which workspace is
asking, so the limiter key is the hostname alone.

Uses the same Redis SET NX EX primitive as WorkspaceLock (see locks.py),
keyed by hostname instead of workspace_id+task_type.

Lock key format: ratelimit:domain:<hostname>
"""

from __future__ import annotations

import logging
import os
import time
from urllib.parse import urlparse

import redis

from packages.infrastructure.redis.client import get_redis

logger = logging.getLogger(__name__)

_DEFAULT_MIN_INTERVAL_SECONDS = float(os.environ.get("DOMAIN_FETCH_MIN_INTERVAL_SECONDS", "2.0"))
_DEFAULT_MAX_WAIT_SECONDS = float(os.environ.get("DOMAIN_FETCH_MAX_WAIT_SECONDS", "10.0"))
_POLL_INTERVAL_SECONDS = 0.3


def extract_host(url: str) -> str:
    """Return the lowercased hostname for a URL, e.g. 'boards.greenhouse.io'."""
    return (urlparse(url).hostname or "").lower()


class DomainRateLimiter:
    """Paces outbound fetches to the same hostname across all concurrent callers."""

    def __init__(self, r: redis.Redis | None = None) -> None:
        self._r = r or get_redis()

    def wait_and_acquire(
        self,
        url: str,
        min_interval_seconds: float = _DEFAULT_MIN_INTERVAL_SECONDS,
        max_wait_seconds: float = _DEFAULT_MAX_WAIT_SECONDS,
    ) -> bool:
        """
        Block until no fetch has hit this hostname in the last
        `min_interval_seconds`, then reserve the slot and return True.

        Fails open: if the hostname can't be parsed, or Redis is unreachable,
        or the wait exceeds `max_wait_seconds`, logs a warning and returns
        False so the caller proceeds anyway. A missed JD fetch just leaves
        the job at "discovered" for a later research run to backfill — worse
        to drop it entirely over a rate-limiter hiccup.
        """
        host = extract_host(url)
        if not host:
            return True

        key = f"ratelimit:domain:{host}"
        ttl_seconds = max(1, int(round(min_interval_seconds)))
        deadline = time.monotonic() + max_wait_seconds

        while True:
            try:
                acquired = self._r.set(key, "1", nx=True, ex=ttl_seconds)
            except redis.exceptions.RedisError:
                logger.warning(
                    "DomainRateLimiter: Redis unreachable, proceeding without pacing (host=%s)",
                    host, exc_info=True,
                )
                return False

            if acquired:
                return True

            if time.monotonic() >= deadline:
                logger.warning(
                    "DomainRateLimiter: wait exceeded max_wait=%.1fs for host=%s — proceeding anyway",
                    max_wait_seconds, host,
                )
                return False

            time.sleep(_POLL_INTERVAL_SECONDS)

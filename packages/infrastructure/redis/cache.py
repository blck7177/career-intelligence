"""
Redis cache helpers.

Rules:
  - Only short-lived, rebuildable data goes here
  - Business final state (runs, tasks, jobs) belongs in Postgres
  - Cache key format: cache:<namespace>:<identifier>

Default TTLs:
  - source_registry:   5 minutes
  - run_status:        30 seconds (polling shortcut)
  - rate_limit:        per-window
"""

from __future__ import annotations

import json
import logging
from typing import Any

import redis

from packages.infrastructure.redis.client import get_redis

logger = logging.getLogger(__name__)


class Cache:
    def __init__(self, r: redis.Redis | None = None) -> None:
        self._r = r or get_redis()

    # ------------------------------------------------------------------
    # Generic get/set
    # ------------------------------------------------------------------

    def get(self, key: str) -> Any | None:
        raw = self._r.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw

    def set(self, key: str, value: Any, ttl: int = 300) -> None:
        self._r.set(key, json.dumps(value), ex=ttl)

    def delete(self, key: str) -> None:
        self._r.delete(key)

    # ------------------------------------------------------------------
    # Run status cache (UI polling shortcut — NOT source of truth)
    # ------------------------------------------------------------------

    def set_run_status(self, run_id: str, status: str, ttl: int = 30) -> None:
        self.set(f"cache:run_status:{run_id}", {"status": status}, ttl=ttl)

    def get_run_status(self, run_id: str) -> str | None:
        data = self.get(f"cache:run_status:{run_id}")
        return data["status"] if data else None

    # ------------------------------------------------------------------
    # Rate limiting (token bucket via Redis INCR + EXPIRE)
    # ------------------------------------------------------------------

    def check_rate_limit(
        self,
        namespace: str,
        identifier: str,
        max_calls: int,
        window_seconds: int,
    ) -> tuple[bool, int]:
        """
        Increment counter for identifier within window.
        Returns (allowed: bool, current_count: int).
        """
        key = f"rate:{namespace}:{identifier}"
        count = self._r.incr(key)
        if count == 1:
            self._r.expire(key, window_seconds)
        allowed = count <= max_calls
        return allowed, int(count)

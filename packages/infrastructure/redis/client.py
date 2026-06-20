"""Shared Redis client factory."""

from __future__ import annotations

import os

import redis

_REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    """Return a shared Redis client (lazy singleton)."""
    global _client
    if _client is None:
        _client = redis.from_url(_REDIS_URL, decode_responses=True)
    return _client

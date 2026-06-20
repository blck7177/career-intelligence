"""
Distributed locks via Redis.

Prevents duplicate concurrent executions for the same workspace+task_type.

Lock key format: lock:workspace:<workspace_id>:<task_type>
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Generator

import redis

from packages.infrastructure.redis.client import get_redis

logger = logging.getLogger(__name__)

_DEFAULT_TTL = 1800  # 30 minutes — long enough for any agent task


class WorkspaceLock:
    """
    Thin wrapper around Redis SET NX EX (acquire) / DEL (release).
    Use as a context manager to guarantee release on exception.
    """

    def __init__(self, r: redis.Redis | None = None) -> None:
        self._r = r or get_redis()

    def _key(self, workspace_id: str, task_type: str) -> str:
        return f"lock:workspace:{workspace_id}:{task_type}"

    def acquire(
        self,
        workspace_id: str,
        task_type: str,
        ttl: int = _DEFAULT_TTL,
        owner: str = "worker",
    ) -> bool:
        """
        Try to acquire the lock.
        Returns True if acquired, False if already held.
        """
        key = self._key(workspace_id, task_type)
        acquired = self._r.set(key, owner, nx=True, ex=ttl)
        if acquired:
            logger.debug("Lock acquired: %s (owner=%s ttl=%ds)", key, owner, ttl)
        else:
            holder = self._r.get(key)
            logger.warning("Lock already held: %s (holder=%s)", key, holder)
        return bool(acquired)

    def release(self, workspace_id: str, task_type: str) -> None:
        key = self._key(workspace_id, task_type)
        self._r.delete(key)
        logger.debug("Lock released: %s", key)

    def is_held(self, workspace_id: str, task_type: str) -> bool:
        return self._r.exists(self._key(workspace_id, task_type)) > 0

    @contextmanager
    def held(
        self,
        workspace_id: str,
        task_type: str,
        ttl: int = _DEFAULT_TTL,
        owner: str = "worker",
    ) -> Generator[bool, None, None]:
        """
        Context manager: acquires lock on enter, releases on exit.
        Yields True if acquired, False if lock was already held.
        Caller should check the yielded value before doing exclusive work.
        """
        acquired = self.acquire(workspace_id, task_type, ttl=ttl, owner=owner)
        try:
            yield acquired
        finally:
            if acquired:
                self.release(workspace_id, task_type)

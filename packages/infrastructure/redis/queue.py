"""
Redis task queue.

Only task_id is enqueued — the full payload lives in Postgres.
Worker reads Postgres after consuming from the queue.

Queue key format: queue:<queue_name>
Default queue: queue:tasks
"""

from __future__ import annotations

import json
import logging

import redis

from packages.infrastructure.redis.client import get_redis

logger = logging.getLogger(__name__)

_DEFAULT_QUEUE = "queue:tasks"


class TaskQueue:
    """
    Simple FIFO queue backed by a Redis list.
    Wraps Celery envelope serialization for non-Celery use (e.g. tests).
    For production use, Celery uses its own Redis broker — this class is
    used by the API to sanity-check / inspect queued items.
    """

    def __init__(self, queue_name: str = _DEFAULT_QUEUE, r: redis.Redis | None = None) -> None:
        self._queue = queue_name
        self._r = r or get_redis()

    def enqueue(self, envelope: dict) -> None:
        """Push a task envelope onto the queue (left push, right pop = FIFO)."""
        payload = json.dumps(envelope)
        self._r.lpush(self._queue, payload)
        logger.debug("Enqueued task: %s → %s", envelope.get("task_id"), self._queue)

    def depth(self) -> int:
        """Current queue depth."""
        return self._r.llen(self._queue)

    def peek(self, count: int = 5) -> list[dict]:
        """Non-destructive peek at the next N items (FIFO order)."""
        raw = self._r.lrange(self._queue, -count, -1)
        return [json.loads(item) for item in reversed(raw)]

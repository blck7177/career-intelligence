"""
Celery application.

Broker:  Redis (REDIS_URL)
Backend: Redis (REDIS_URL) — only used for task result tracking, not business state

Queue names:
  tasks    — default task queue
  agent    — (future) high-priority agent tasks

Rules (from AGENTS.md):
  - Worker does not expose HTTP endpoints
  - Worker does not return data to the frontend directly
  - Worker writes results to Postgres, not Redis
"""

from __future__ import annotations

import os

from celery import Celery

_REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "career_worker",
    broker=_REDIS_URL,
    backend=_REDIS_URL,
    include=["apps.worker.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,          # ack only after task completes (safe retry on crash)
    worker_prefetch_multiplier=1, # one task at a time per worker (agent tasks are long)
    task_routes={
        "apps.worker.tasks.execute_task": {"queue": "tasks"},
    },
    beat_schedule={},  # no periodic tasks in MVP
)

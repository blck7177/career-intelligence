"""
Celery application.

Broker:  Redis (REDIS_URL)
Backend: Redis (REDIS_URL) — only used for task result tracking, not business state

Queue names:
  fast   — deterministic tasks: job_report, fit_report (prefork pool, low latency)
  agent  — OpenClaw agent tasks: job_discovery, job_research, run_reflection
            (gevent pool — a single invoke() call blocks on network I/O for
            up to the run's full timeout budget, so prefork would tie up a
            whole OS process per in-flight call; gevent holds many
            concurrent invocations per process instead). See
            docker-compose.dev.yml for the current --pool/--concurrency
            values, and dev_note/career/phase20-launch-hardening/
            gevent_pool_plan_0713/README.md for why.

Two separate worker services prevent agent tasks from blocking fast deterministic tasks.
See docker-compose.dev.yml: worker-fast + worker-agent.

Rules (from AGENTS.md):
  - Worker does not expose HTTP endpoints
  - Worker does not return data to the frontend directly
  - Worker writes results to Postgres, not Redis
"""

from __future__ import annotations

import os

from celery import Celery
from celery.signals import worker_process_init

from packages.infrastructure.observability.logging import configure_logging


@worker_process_init.connect
def _setup_logging(**_kwargs) -> None:
    """Configure structured logging for every Celery worker process."""
    configure_logging()


@worker_process_init.connect
def _patch_psycopg_for_gevent(**_kwargs) -> None:
    """
    Patch psycopg2 to cooperate with gevent's monkey-patched socket layer.

    psycopg2 is a C extension that talks to libpq directly, bypassing
    Python's socket module — gevent's monkey-patch has no effect on it, so
    a blocked query would otherwise stall every other greenlet in the
    process. No-op when this worker isn't running under the gevent pool
    (gevent.monkey.patch_all() only runs when Celery's gevent pool starts).
    """
    try:
        from gevent import monkey
    except ImportError:
        return
    if not monkey.is_module_patched("socket"):
        return
    from psycogreen.gevent import patch_psycopg

    patch_psycopg()

_REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "career_worker",
    broker=_REDIS_URL,
    backend=_REDIS_URL,
    include=["apps.worker.tasks.execute_task"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,          # ack only after task completes (safe retry on crash)
    worker_prefetch_multiplier=1, # one task at a time per worker process
    # Queue routing is determined at enqueue time (in apps/api/routes/runs.py):
    #   agent.* tasks → queue="agent"  (consumed by worker-agent, concurrency=1)
    #   deterministic tasks → queue="fast" (consumed by worker-fast, concurrency=2-4)
    # Default queue when not specified: fast
    task_default_queue="fast",
    beat_schedule={},  # no periodic tasks in MVP
)


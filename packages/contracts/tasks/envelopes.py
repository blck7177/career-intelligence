"""
Task queue message envelope.
Only IDs are passed via Redis/Celery — full payload is read from Postgres.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class TaskEnvelope(BaseModel):
    """
    The only thing sent via Redis/Celery.
    Worker reads full payload from Postgres using task_id.
    """

    task_id: str
    run_id: str
    workspace_id: str
    task_type: str
    schema_version: str = "v1"
    idempotency_key: str
    attempt: int = 1
    created_at: datetime = Field(default_factory=datetime.utcnow)

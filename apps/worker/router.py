"""
Task router: maps task_type → ExecutionMode.

This is a thin dispatcher layer.
Actual routing logic lives in packages/domain/agent_jobs/routing.py.
"""

from __future__ import annotations

import logging

from packages.contracts.tasks.envelopes import TaskEnvelope
from packages.domain.agent_jobs.routing import ExecutionMode, route_task

logger = logging.getLogger(__name__)


def dispatch(envelope: TaskEnvelope) -> ExecutionMode:
    """
    Determine execution mode for this task.
    Called by execute_task() before handing off to the right handler.
    """
    mode = route_task(envelope.task_type)
    logger.info(
        "Routing task %s (type=%s) → %s",
        envelope.task_id,
        envelope.task_type,
        mode.value,
    )
    return mode

"""
Task routing: determines whether a task_type runs via OpenClaw or deterministic Python.

This is pure domain logic — no IO imports.
"""

from __future__ import annotations

from enum import Enum


class ExecutionMode(str, Enum):
    OPENCLAW = "openclaw"
    DETERMINISTIC = "deterministic"


# Task types that run via OpenClaw agent runtime
_OPENCLAW_TASK_TYPES: frozenset[str] = frozenset(
    {
        "agent.job_discovery",
        "agent.job_research",
        "agent.run_reflection",
    }
)

# Map task_type → agent_id
_TASK_TYPE_TO_AGENT: dict[str, str] = {
    "agent.job_discovery": "career-search-agent",
    "agent.job_research": "career-research-agent",
    "agent.run_reflection": "career-reflect-agent",
}

# Skill contract version per agent
_AGENT_SKILL_VERSIONS: dict[str, str] = {
    "career-search-agent": "career-search-v1",
    "career-research-agent": "career-research-v1",
    "career-reflect-agent": "career-reflect-v1",
}


def route_task(task_type: str) -> ExecutionMode:
    if task_type in _OPENCLAW_TASK_TYPES:
        return ExecutionMode.OPENCLAW
    return ExecutionMode.DETERMINISTIC


def celery_queue_for_task_type(task_type: str) -> str:
    """
    Return the Celery queue name for a given task_type.

    agent tasks  → "agent"  (worker-agent: concurrency=1, long-running OpenClaw jobs)
    fast tasks   → "fast"   (worker-fast: concurrency=2-4, deterministic short tasks)

    Used by the API when enqueuing tasks so agent and deterministic tasks are
    isolated and cannot block each other.
    """
    return "agent" if task_type in _OPENCLAW_TASK_TYPES else "fast"


def get_agent_id(task_type: str) -> str:
    if task_type not in _TASK_TYPE_TO_AGENT:
        raise ValueError(f"No agent mapped for task_type: {task_type!r}")
    return _TASK_TYPE_TO_AGENT[task_type]


def get_skill_version(agent_id: str) -> str:
    if agent_id not in _AGENT_SKILL_VERSIONS:
        raise ValueError(f"No skill version for agent_id: {agent_id!r}")
    return _AGENT_SKILL_VERSIONS[agent_id]

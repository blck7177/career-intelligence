"""
Agent invocation contracts.

AgentInvocationSpec  — input to agent_runtime.invoke()
AgentInvocationResult — raw output from agent_runtime.invoke()
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


class AgentInvocationSpec(BaseModel):
    """
    Describes a single bounded agent execution.
    Built by domain/agent_jobs/planner.py, consumed by infrastructure/agent_runtime.
    """

    invocation_id: str
    run_id: str
    task_id: str
    workspace_id: str

    agent_id: str
    skill_contract_version: str
    session_key: str  # platform-generated, never from frontend

    # Paths on the shared agent_artifacts volume
    input_spec_path: str   # worker writes this before invoke
    output_manifest_path: str  # agent writes this before stopping

    timeout_seconds: int = Field(default=900, ge=60, le=3600)
    max_tool_calls: int = Field(default=30, ge=1, le=200)
    allowed_output_types: list[str] = Field(default_factory=list)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AgentInvocationResult(BaseModel):
    """Raw result captured from agent_runtime.invoke()."""

    invocation_id: str
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False
    tool_activity_summary_path: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


class AgentTaskInput(BaseModel):
    """
    Serialized to input.json on the agent_artifacts volume.
    Agent reads this to understand its task.
    """

    invocation_id: str
    run_id: str
    task_id: str
    workspace_id: str
    task_type: str
    skill_contract_version: str

    output_manifest_path: str
    budget: AgentBudget

    # Task-type-specific payload; agents read from here
    payload: dict


class AgentBudget(BaseModel):
    max_tool_calls: int = 30
    max_candidates: int = 50
    max_new_sources: int = 10
    timeout_seconds: int = 900

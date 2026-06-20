"""
AgentInvocationSpec builder.

Builds the spec that agent_runtime.invoke() consumes.
Pure domain logic — no IO imports.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from packages.contracts.agents.invocation import AgentBudget, AgentInvocationSpec, AgentTaskInput
from packages.domain.agent_jobs.routing import get_agent_id, get_skill_version


def build_session_key(
    agent_id: str,
    workspace_id: str,
    run_id: str,
    task_id: str,
    attempt: int,
) -> str:
    """
    Generate a platform-controlled session key.
    Never accepts session keys from frontend or user input.
    Each run/task/attempt gets a unique, isolated session.
    """
    return (
        f"agent:{agent_id}"
        f":workspace:{workspace_id}"
        f":run:{run_id}"
        f":task:{task_id}"
        f":attempt:{attempt}"
    )


def build_invocation_spec(
    *,
    run_id: str,
    task_id: str,
    workspace_id: str,
    task_type: str,
    attempt: int,
    artifacts_base_dir: str,
    payload: dict,
    budget: AgentBudget | None = None,
) -> AgentInvocationSpec:
    """
    Build an AgentInvocationSpec for a given task.
    Called by the worker before invoking agent_runtime.
    """
    agent_id = get_agent_id(task_type)
    skill_version = get_skill_version(agent_id)
    session_key = build_session_key(agent_id, workspace_id, run_id, task_id, attempt)
    invocation_id = f"ainv_{uuid.uuid4().hex[:12]}"

    run_dir = Path(artifacts_base_dir) / run_id / task_id
    input_spec_path = str(run_dir / "input.json")
    output_manifest_path = str(run_dir / "output_manifest.json")

    if budget is None:
        budget = AgentBudget()

    return AgentInvocationSpec(
        invocation_id=invocation_id,
        run_id=run_id,
        task_id=task_id,
        workspace_id=workspace_id,
        agent_id=agent_id,
        skill_contract_version=skill_version,
        session_key=session_key,
        input_spec_path=input_spec_path,
        output_manifest_path=output_manifest_path,
        timeout_seconds=budget.timeout_seconds,
        max_tool_calls=budget.max_tool_calls,
        created_at=datetime.now(timezone.utc),
    )


def build_task_input(
    *,
    spec: AgentInvocationSpec,
    task_type: str,
    payload: dict,
    budget: AgentBudget,
) -> AgentTaskInput:
    """Build the AgentTaskInput that gets serialized to input.json."""
    return AgentTaskInput(
        invocation_id=spec.invocation_id,
        run_id=spec.run_id,
        task_id=spec.task_id,
        workspace_id=spec.workspace_id,
        task_type=task_type,
        skill_contract_version=spec.skill_contract_version,
        output_manifest_path=spec.output_manifest_path,
        budget=budget,
        payload=payload,
    )

"""
Agent invocation message builder.

Transport-agnostic: the same message text is passed as the CLI --message
argument (OpenClawGatewayRuntime) and as the HTTP chat-completion user
message (OpenClawHttpRuntime). Extracted here so both runtimes share one
implementation instead of duplicating it.
"""

from __future__ import annotations

import logging
from pathlib import Path

from packages.contracts.agents.invocation import AgentInvocationSpec

logger = logging.getLogger(__name__)


def build_invocation_message(spec: AgentInvocationSpec) -> str:
    """
    Build the invocation message passed to the agent.

    The full task spec is embedded inline so the agent never needs to read
    a file from outside its workspace sandbox.  The output_manifest_path is
    still included as a write target because the agent uses approved exec
    wrappers (career_write_manifest.py) to produce it — those scripts run
    inside the gateway and have access to /app/data/agent_artifacts.
    """
    # Read the task spec that the caller wrote to the shared volume.
    # Embedding it here prevents the codex embedded-runner from needing to
    # sandbox-escape to /app/data/agent_artifacts to read the file.
    try:
        task_spec_json = Path(spec.input_spec_path).read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning(
            "Could not read input_spec_path for inline embedding: %s — "
            "agent will be given path only (may fail in sandbox)", exc
        )
        task_spec_json = None

    if task_spec_json:
        spec_block = (
            f"Your task spec (full JSON — do NOT read from file, use this directly):\n\n"
            f"```json\n{task_spec_json}\n```"
        )
    else:
        spec_block = (
            f"Read your task spec from:\n"
            f"  {spec.input_spec_path}"
        )

    evidence_paragraph = _evidence_instructions(spec.agent_id)

    return (
        f"Agent: {spec.agent_id}\n"
        f"Invocation ID: {spec.invocation_id}\n\n"
        f"{spec_block}\n\n"
        f"Call career_write_manifest before stopping. The wrapper writes the "
        f"platform manifest to the canonical path derived from your task spec "
        f"(expected: {spec.output_manifest_path}). Do not pass a hand-copied "
        f"manifest path to --output.\n\n"
        f"{evidence_paragraph}\n\n"
        f"Follow the active skill instructions.\n"
        f"Do not write to the database.\n"
        f"Do not modify files outside your designated run directory.\n"
        f"Stop after writing the manifest."
    )


def _evidence_instructions(agent_id: str) -> str:
    """Return the agent-type-specific evidence paragraph for the invocation message."""
    if agent_id == "career-reflect-agent":
        return (
            "This is a real production run. You MUST analyze the provided run "
            "artifacts (coverage report, search ledger, candidate pool) before "
            "writing the manifest. Do NOT write placeholder or mock output. "
            "Do NOT mark status as completed or partial without genuine analysis "
            "of the prior run's results. "
            "strategy_patch.json MUST be a flat object with only the 7 allowed "
            "fields (effective_sources, avoid_sources, effective_query_patterns, "
            "avoid_query_patterns, coverage_by_role_category, key_learnings, "
            "recommended_next_searches). Do NOT wrap it in run_id, patches, "
            "operations, or other metadata."
        )
    return (
        "This is a real production run. You MUST perform genuine discovery "
        "actions (web_search, web_fetch, or approved exec wrappers) before "
        "writing the manifest. Do NOT write placeholder or mock output. "
        "Do NOT mark status as completed or partial without real tool calls "
        "that support it."
    )

#!/usr/bin/env python3
"""
career_search_status — Query current search session budget and coverage.

Usage:
    python career_search_status.py --task-spec <path> --output <path>

This wrapper is in the OpenClaw exec allowlist.
It accepts only --task-spec and --output arguments.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click


@click.command()
@click.option("--task-spec", required=True, type=click.Path(exists=True), help="Path to task spec JSON")
@click.option("--output", required=True, type=click.Path(), help="Path to write output JSON")
def main(task_spec: str, output: str) -> None:
    try:
        spec = json.loads(Path(task_spec).read_text())
    except Exception as exc:
        _fail(output, f"Failed to read task spec: {exc}")
        sys.exit(1)

    run_id = spec.get("run_id", "")
    task_id = spec.get("task_id", "")
    budget = spec.get("budget", {})

    # Read candidate pool to count logged candidates
    artifacts_dir = Path(spec.get("artifacts_dir", "/app/data/agent_artifacts"))
    candidate_pool_path = artifacts_dir / run_id / task_id / "candidate_pool.jsonl"

    candidates_logged = 0
    if candidate_pool_path.exists():
        candidates_logged = sum(1 for line in candidate_pool_path.read_text().splitlines() if line.strip())

    # Read trace events to count tool calls
    trace_path = artifacts_dir / run_id / task_id / "trace_events.jsonl"
    tool_calls_used = 0
    if trace_path.exists():
        tool_calls_used = sum(1 for line in trace_path.read_text().splitlines() if line.strip())

    max_candidates = budget.get("max_candidates", 50)
    max_tool_calls = budget.get("max_tool_calls", 30)

    result = {
        "candidates_logged": candidates_logged,
        "tool_calls_used": tool_calls_used,
        "budget_remaining": {
            "candidates": max(0, max_candidates - candidates_logged),
            "tool_calls": max(0, max_tool_calls - tool_calls_used),
        },
        "run_id": run_id,
        "task_id": task_id,
    }

    Path(output).write_text(json.dumps(result, indent=2))


def _fail(output: str, message: str) -> None:
    Path(output).write_text(json.dumps({"error": message}))
    click.echo(f"ERROR: {message}", err=True)


if __name__ == "__main__":
    main()

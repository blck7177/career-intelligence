#!/usr/bin/env python3
"""
career_log_candidates — Append triaged candidates to the candidate pool.

Usage:
    python career_log_candidates.py --task-spec <path> --output <path>

task-spec JSON must contain:
  - run_id, task_id, artifacts_dir
  - candidates: list of { url, title, company, source_type, notes? }

This wrapper is in the OpenClaw exec allowlist.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import click


REQUIRED_CANDIDATE_FIELDS = {"url", "title", "company", "source_type"}


@click.command()
@click.option("--task-spec", required=True, type=click.Path(exists=True))
@click.option("--output", required=True, type=click.Path())
def main(task_spec: str, output: str) -> None:
    try:
        spec = json.loads(Path(task_spec).read_text())
    except Exception as exc:
        _fail(output, f"Failed to read task spec: {exc}")
        sys.exit(1)

    run_id = spec.get("run_id", "")
    task_id = spec.get("task_id", "")
    candidates = spec.get("candidates", [])
    artifacts_dir = Path(spec.get("artifacts_dir", "/app/data/agent_artifacts"))

    if not isinstance(candidates, list):
        _fail(output, "'candidates' must be a list")
        sys.exit(1)

    pool_path = artifacts_dir / run_id / task_id / "candidate_pool.jsonl"
    pool_path.parent.mkdir(parents=True, exist_ok=True)

    logged = []
    errors = []

    for i, candidate in enumerate(candidates):
        missing = REQUIRED_CANDIDATE_FIELDS - set(candidate.keys())
        if missing:
            errors.append({"index": i, "error": f"Missing fields: {missing}"})
            continue

        if not candidate["url"].startswith(("http://", "https://")):
            errors.append({"index": i, "error": "url must start with http:// or https://"})
            continue

        entry = {
            **candidate,
            "logged_at": datetime.now(timezone.utc).isoformat(),
            "run_id": run_id,
            "task_id": task_id,
        }

        with pool_path.open("a") as f:
            f.write(json.dumps(entry) + "\n")

        logged.append(candidate["url"])

    result = {
        "logged_count": len(logged),
        "logged_urls": logged,
        "errors": errors,
    }

    Path(output).write_text(json.dumps(result, indent=2))

    if errors:
        click.echo(f"WARNING: {len(errors)} candidates skipped due to validation errors", err=True)


def _fail(output: str, message: str) -> None:
    Path(output).write_text(json.dumps({"error": message}))
    click.echo(f"ERROR: {message}", err=True)


if __name__ == "__main__":
    main()

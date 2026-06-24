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

import hashlib
import json
import os
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

    # Append a trace event for backward-compatibility (GatewayTransportValidator reads this).
    # Written even when logged_count == 0 (captures attempted log with validation errors).
    if run_id and task_id:
        trace_path = artifacts_dir / run_id / task_id / "trace_events.jsonl"
        trace_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tool_name": "career_log_candidates",
            "run_id": run_id,
            "task_id": task_id,
            "status": "ok",
            "logged_count": len(logged),
        }
        with trace_path.open("a") as f:
            f.write(json.dumps(trace_entry) + "\n")

    # Append a signed ledger event so ToolLedgerValidator can verify real discovery.
    signing_key = os.environ.get("TOOL_LEDGER_SIGNING_KEY", "")
    tool_events_path_str = spec.get("output_paths", {}).get("tool_events_path", "")
    if tool_events_path_str and signing_key:
        try:
            sys.path.insert(0, "/app")  # PYTHONPATH is stripped by OpenClaw exec security policy
            from packages.infrastructure.tool_ledger import append_signed_event  # noqa: PLC0415

            pool_bytes = pool_path.read_bytes()
            pool_hash = "sha256:" + hashlib.sha256(pool_bytes).hexdigest()
            # Use total pool line count (not just this call's logged count) so that
            # DiscoveryEvidenceValidator.candidate_count == pool actual lines even when
            # career_log_candidates is called multiple times across a run.
            pool_count = sum(1 for line in pool_bytes.decode().splitlines() if line.strip())
            invocation_id = spec.get("invocation_id", "")
            append_signed_event(
                Path(tool_events_path_str),
                {
                    "invocation_id": invocation_id,
                    "run_id": run_id,
                    "task_id": task_id,
                    "tool_name": "career_log_candidates",
                    "event_type": "candidate_log",
                    "status": "ok",
                    "candidate_count": pool_count,
                    "output_path": str(pool_path),
                    "output_hash": pool_hash,
                },
                signing_key,
            )
        except Exception as exc:  # noqa: BLE001
            click.echo(f"WARNING: failed to append signed ledger event: {exc}", err=True)

    if errors:
        click.echo(f"WARNING: {len(errors)} candidates skipped due to validation errors", err=True)


def _fail(output: str, message: str) -> None:
    Path(output).write_text(json.dumps({"error": message}))
    click.echo(f"ERROR: {message}", err=True)


if __name__ == "__main__":
    main()

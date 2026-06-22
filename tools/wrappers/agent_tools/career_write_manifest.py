#!/usr/bin/env python3
"""
career_write_manifest — Write the agent output manifest to the designated path.

Usage:
    python career_write_manifest.py --task-spec <path> --output <path>

task-spec JSON must contain:
  - invocation_id, status, stop_reason
  - artifact_paths: dict of artifact_type → file path
  - summary: dict of stats

This is the LAST wrapper the agent calls before stopping.
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


VALID_STATUSES = {"completed", "partial", "failed"}


@click.command()
@click.option("--task-spec", required=True, type=click.Path(exists=True))
@click.option("--output", required=True, type=click.Path())
def main(task_spec: str, output: str) -> None:
    try:
        spec = json.loads(Path(task_spec).read_text())
    except Exception as exc:
        _fail(output, f"Failed to read task spec: {exc}")
        sys.exit(1)

    status = spec.get("status", "")
    if status not in VALID_STATUSES:
        _fail(output, f"status must be one of {VALID_STATUSES}, got: {status!r}")
        sys.exit(1)

    summary = spec.get("summary", {})

    # Promote discovery summary fields to top-level so DiscoveryManifest.model_validate()
    # can read them directly. The agent may supply them inside summary{} or at top-level;
    # top-level wins, then summary, then default.
    candidate_count = spec.get("candidate_count", summary.get("candidate_count", 0))
    sources_tried = spec.get("sources_tried", summary.get("sources_tried", []))
    sources_added = spec.get("sources_added", summary.get("sources_added", []))

    manifest = {
        "invocation_id": spec.get("invocation_id", ""),
        "status": status,
        "stop_reason": spec.get("stop_reason", ""),
        "artifact_paths": spec.get("artifact_paths", {}),
        "summary": summary,
        "candidate_count": candidate_count,
        "sources_tried": sources_tried,
        "sources_added": sources_added,
        "written_at": datetime.now(timezone.utc).isoformat(),
    }

    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(manifest, indent=2))

    # Append a signed ledger event so ToolLedgerValidator can verify manifest provenance.
    signing_key = os.environ.get("TOOL_LEDGER_SIGNING_KEY", "")
    tool_events_path_str = spec.get("output_paths", {}).get("tool_events_path", "")
    if tool_events_path_str and signing_key:
        try:
            from packages.infrastructure.tool_ledger import append_signed_event  # noqa: PLC0415

            manifest_hash = "sha256:" + hashlib.sha256(output_path.read_bytes()).hexdigest()
            invocation_id = spec.get("invocation_id", "")
            run_id = spec.get("run_id", "")
            task_id = spec.get("task_id", "")
            append_signed_event(
                Path(tool_events_path_str),
                {
                    "invocation_id": invocation_id,
                    "run_id": run_id,
                    "task_id": task_id,
                    "tool_name": "career_write_manifest",
                    "event_type": "manifest_write",
                    "status": "ok",
                    "candidate_count": candidate_count,
                    "output_path": str(output_path),
                    "output_hash": manifest_hash,
                },
                signing_key,
            )
        except Exception as exc:  # noqa: BLE001
            click.echo(f"WARNING: failed to append signed ledger event: {exc}", err=True)

    click.echo(f"Manifest written to {output}", err=True)


def _fail(output: str, message: str) -> None:
    Path(output).write_text(json.dumps({"error": message, "status": "failed"}))
    click.echo(f"ERROR: {message}", err=True)


if __name__ == "__main__":
    main()

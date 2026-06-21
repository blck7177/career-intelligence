#!/usr/bin/env python3
"""
career_fetch_source — Fetch and normalize a job posting from an ATS source URL.

Usage:
    python career_fetch_source.py --task-spec <path> --output <path>

task-spec JSON must contain:
  - url: the ATS job posting URL
  - source_type: greenhouse | lever | ashby | workday | html_fallback
  - run_id, task_id, artifacts_dir

This wrapper is in the OpenClaw exec allowlist.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import click
import httpx


ALLOWED_SOURCE_TYPES = {"greenhouse", "lever", "ashby", "workday", "html_fallback"}


@click.command()
@click.option("--task-spec", required=True, type=click.Path(exists=True))
@click.option("--output", required=True, type=click.Path())
def main(task_spec: str, output: str) -> None:
    try:
        spec = json.loads(Path(task_spec).read_text())
    except Exception as exc:
        _fail(output, f"Failed to read task spec: {exc}")
        sys.exit(1)

    url = spec.get("url", "")
    source_type = spec.get("source_type", "html_fallback")
    run_id = spec.get("run_id", "")
    task_id = spec.get("task_id", "")
    artifacts_dir = Path(spec.get("artifacts_dir", "/app/data/agent_artifacts"))

    if not url.startswith(("http://", "https://")):
        _fail(output, f"Invalid URL: {url!r}")
        sys.exit(1)

    if source_type not in ALLOWED_SOURCE_TYPES:
        _fail(output, f"source_type must be one of {ALLOWED_SOURCE_TYPES}")
        sys.exit(1)

    try:
        response = httpx.get(url, follow_redirects=True, timeout=15)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        _fail(output, f"HTTP {exc.response.status_code} fetching {url}")
        sys.exit(1)
    except Exception as exc:
        _fail(output, f"Failed to fetch {url}: {exc}")
        sys.exit(1)

    result = {
        "url": url,
        "source_type": source_type,
        "status_code": response.status_code,
        "content_length": len(response.text),
        "text": response.text[:50000],  # cap at 50k chars
        "final_url": str(response.url),
    }

    Path(output).write_text(json.dumps(result, indent=2))

    # Append a trace event so ToolActivityValidator can confirm real discovery action occurred.
    if run_id and task_id:
        trace_path = artifacts_dir / run_id / task_id / "trace_events.jsonl"
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        trace_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tool_name": "career_fetch_source",
            "run_id": run_id,
            "task_id": task_id,
            "status": "ok",
            "url": url,
            "source_type": source_type,
        }
        with trace_path.open("a") as f:
            f.write(json.dumps(trace_entry) + "\n")


def _fail(output: str, message: str) -> None:
    Path(output).write_text(json.dumps({"error": message}))
    click.echo(f"ERROR: {message}", err=True)


if __name__ == "__main__":
    main()

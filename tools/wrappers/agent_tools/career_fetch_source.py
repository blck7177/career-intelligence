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

from packages.infrastructure.jd_fetch.service import (
    fetch_jd_from_url,
    save_fetched_jd_artifact,
)
from packages.infrastructure.redis.domain_rate_limiter import DomainRateLimiter


ALLOWED_SOURCE_TYPES = {"greenhouse", "lever", "ashby", "workday", "html_fallback"}

# fetch_result.source == "ats_api" means the posting was resolved from the
# ATS's own structured JSON API (see jd_fetch.service._fetch_via_ats_api) —
# realness is guaranteed by that API's contract, not by reading this text, so
# the agent only needs enough to judge relevance/seniority, not to re-verify
# it's a real posting. Everything else still needs the fuller excerpt because
# the agent's realness check IS the returned text in that case.
_AGENT_VISIBLE_CHARS_ATS_API = 1500
_AGENT_VISIBLE_CHARS_SCRAPED = 50000


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

    DomainRateLimiter().wait_and_acquire(url)
    fetch_result = fetch_jd_from_url(url)
    if not fetch_result.ok:
        _fail(output, fetch_result.error or "Fetch failed")
        sys.exit(1)

    artifact_dir = artifacts_dir / run_id / task_id if run_id and task_id else artifacts_dir
    jd_text_path: str | None = None
    jd_hash: str | None = fetch_result.jd_hash

    if run_id and task_id and fetch_result.jd_text:
        try:
            text_path, _, jd_hash = save_fetched_jd_artifact(
                artifact_dir=artifact_dir,
                url=url,
                raw_content=fetch_result.jd_text,
                content_type="text/plain",
            )
            jd_text_path = str(text_path)
        except ValueError as exc:
            _fail(output, str(exc))
            sys.exit(1)

    full_text = fetch_result.jd_text or ""
    via_ats_api = fetch_result.source == "ats_api"
    visible_chars = _AGENT_VISIBLE_CHARS_ATS_API if via_ats_api else _AGENT_VISIBLE_CHARS_SCRAPED

    result = {
        "url": url,
        "source_type": source_type,
        "status_code": 200,
        "content_length": len(full_text),
        "text": full_text[:visible_chars],
        "final_url": url,
        "jd_text_path": jd_text_path,
        "jd_hash": jd_hash,
    }
    if via_ats_api:
        result["note"] = (
            "Resolved via the ATS's structured API — this is a confirmed real "
            "posting, no need to re-verify. Text is truncated to an excerpt "
            "for your relevance/seniority judgment; the full description is "
            "already persisted for downstream use."
        )

    Path(output).write_text(json.dumps(result, indent=2))

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
            "jd_source": fetch_result.source,
        }
        with trace_path.open("a") as f:
            f.write(json.dumps(trace_entry) + "\n")


def _fail(output: str, message: str) -> None:
    Path(output).write_text(json.dumps({"error": message}))
    click.echo(f"ERROR: {message}", err=True)
    click.echo(f"career_fetch_source failed: {message}")


if __name__ == "__main__":
    main()

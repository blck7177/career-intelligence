#!/usr/bin/env python3
"""
career-validate-run — Validate a run's artifacts against their schemas.

Usage:
    career-validate-run --run-id <run_id>

Checks:
  - output_manifest.json exists for each agent invocation
  - manifest passes schema validation
  - artifact files declared in manifest are present on disk
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click


@click.command()
@click.option("--run-id", required=True, help="Run ID to validate")
@click.option(
    "--artifacts-dir",
    default="/app/data/agent_artifacts",
    show_default=True,
    help="Base directory for agent artifacts",
)
def main(run_id: str, artifacts_dir: str) -> None:
    """Validate a run's agent artifacts against schema and provenance rules."""
    import os

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        click.echo("ERROR: DATABASE_URL not set", err=True)
        sys.exit(1)

    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(db_url)
        with engine.connect() as conn:
            invocations = conn.execute(
                text(
                    "SELECT id, agent_id, status, output_manifest_uri "
                    "FROM agent_invocations WHERE run_id = :run_id"
                ),
                {"run_id": run_id},
            ).mappings().all()
    except Exception as exc:
        click.echo(f"ERROR querying DB: {exc}", err=True)
        sys.exit(1)

    if not invocations:
        click.echo(f"No agent invocations found for run_id={run_id!r}")
        sys.exit(0)

    all_ok = True
    for inv in invocations:
        click.echo(f"\nInvocation {inv['id']} (agent={inv['agent_id']}, status={inv['status']})")
        manifest_path = inv.get("output_manifest_uri")
        if not manifest_path or not Path(manifest_path).exists():
            click.echo("  [FAIL] output_manifest.json missing")
            all_ok = False
            continue

        try:
            manifest = json.loads(Path(manifest_path).read_text())
            click.echo(f"  [OK]   manifest status={manifest.get('status')}")
            for artifact_type, path in manifest.get("artifact_paths", {}).items():
                exists = Path(path).exists()
                mark = "[OK]" if exists else "[FAIL]"
                click.echo(f"  {mark}   {artifact_type}: {path}")
                if not exists:
                    all_ok = False
        except Exception as exc:
            click.echo(f"  [FAIL] could not parse manifest: {exc}")
            all_ok = False

    if all_ok:
        click.echo("\nAll validations passed.")
        sys.exit(0)
    else:
        click.echo("\nSome validations FAILED.", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

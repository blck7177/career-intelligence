#!/usr/bin/env python3
"""
career-summarize-run — Print a concise summary of a completed run.

Usage:
    career-summarize-run --run-id <run_id>

Prints:
  - Run status and type
  - Task list with statuses
  - Agent invocations with validation results
  - Artifact count
"""

from __future__ import annotations

import json
import sys

import click


@click.command()
@click.option("--run-id", required=True, help="Run ID to summarize")
@click.option(
    "--format",
    "output_format",
    default="text",
    show_default=True,
    type=click.Choice(["text", "json"]),
)
def main(run_id: str, output_format: str) -> None:
    """Print a concise summary of a run from the database."""
    import os

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        click.echo("ERROR: DATABASE_URL not set", err=True)
        sys.exit(1)

    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(db_url)
        with engine.connect() as conn:
            run = conn.execute(
                text("SELECT * FROM runs WHERE id = :id"), {"id": run_id}
            ).mappings().first()
            if run is None:
                click.echo(f"Run {run_id!r} not found", err=True)
                sys.exit(1)

            tasks = conn.execute(
                text("SELECT id, task_type, status, error_code FROM tasks WHERE run_id = :id"),
                {"id": run_id},
            ).mappings().all()

            invocations = conn.execute(
                text(
                    "SELECT id, agent_id, status, exit_code FROM agent_invocations "
                    "WHERE run_id = :id"
                ),
                {"id": run_id},
            ).mappings().all()

            artifact_count = conn.execute(
                text("SELECT COUNT(*) FROM artifacts WHERE run_id = :id"), {"id": run_id}
            ).scalar()

            event_count = conn.execute(
                text("SELECT COUNT(*) FROM task_events WHERE run_id = :id"), {"id": run_id}
            ).scalar()

    except Exception as exc:
        click.echo(f"ERROR: {exc}", err=True)
        sys.exit(1)

    summary = {
        "run_id": run_id,
        "run_type": run["run_type"],
        "status": run["status"],
        "created_at": str(run["created_at"]),
        "tasks": [dict(t) for t in tasks],
        "agent_invocations": [dict(i) for i in invocations],
        "artifact_count": artifact_count,
        "event_count": event_count,
    }

    if output_format == "json":
        click.echo(json.dumps(summary, indent=2, default=str))
    else:
        click.echo(f"Run:       {run_id}")
        click.echo(f"Type:      {run['run_type']}")
        click.echo(f"Status:    {run['status']}")
        click.echo(f"Created:   {str(run['created_at'])[:19]}")
        click.echo(f"Artifacts: {artifact_count}")
        click.echo(f"Events:    {event_count}")
        click.echo()
        click.echo("Tasks:")
        for t in tasks:
            err = f" (error={t['error_code']})" if t.get("error_code") else ""
            click.echo(f"  {t['id'][:12]}… {t['task_type']:<30} {t['status']}{err}")
        if invocations:
            click.echo()
            click.echo("Agent Invocations:")
            for i in invocations:
                click.echo(
                    f"  {i['id'][:12]}… agent={i['agent_id']:<25} "
                    f"status={i['status']:<15} exit={i['exit_code']}"
                )


if __name__ == "__main__":
    main()

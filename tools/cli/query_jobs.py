#!/usr/bin/env python3
"""
career-query-jobs — Query discovered jobs from the database.

Usage:
    career-query-jobs [OPTIONS]

Options:
    --workspace-id TEXT    Workspace ID to query (required)
    --status TEXT          Filter by job status [default: all]
    --limit INTEGER        Max records to return [default: 50]
    --format [json|table]  Output format [default: table]
"""

from __future__ import annotations

import json
import sys

import click


@click.command()
@click.option("--workspace-id", required=True, help="Workspace ID to query")
@click.option(
    "--status",
    default="all",
    show_default=True,
    help="Filter by status (all | active | archived)",
)
@click.option("--limit", default=50, show_default=True, type=int, help="Max records to return")
@click.option(
    "--format",
    "output_format",
    default="table",
    show_default=True,
    type=click.Choice(["json", "table"]),
    help="Output format",
)
def main(workspace_id: str, status: str, limit: int, output_format: str) -> None:
    """Query discovered jobs from the Postgres database."""
    import os

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        click.echo("ERROR: DATABASE_URL not set", err=True)
        sys.exit(1)

    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(db_url)
        with engine.connect() as conn:
            where = f"workspace_id = :ws"
            params: dict = {"ws": workspace_id, "limit": limit}

            query = text(
                f"SELECT id, source, normalized_json, created_at "
                f"FROM jobs WHERE {where} ORDER BY created_at DESC LIMIT :limit"
            )
            rows = conn.execute(query, params).mappings().all()

    except Exception as exc:
        click.echo(f"ERROR: {exc}", err=True)
        sys.exit(1)

    if output_format == "json":
        click.echo(json.dumps([dict(r) for r in rows], indent=2, default=str))
    else:
        if not rows:
            click.echo("No jobs found.")
            return
        click.echo(f"{'ID':<38} {'SOURCE':<20} {'CREATED_AT'}")
        click.echo("-" * 80)
        for r in rows:
            click.echo(f"{r['id']:<38} {r['source']:<20} {str(r['created_at'])[:19]}")
        click.echo(f"\nTotal: {len(rows)}")


if __name__ == "__main__":
    main()

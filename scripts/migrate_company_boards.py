#!/usr/bin/env python3
"""
One-time migration: import company_boards.yaml into the company_sources DB table.

Usage:
    python scripts/migrate_company_boards.py [--dry-run]
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import click
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.domain.agent_jobs.ats_providers import (
    ATS_PROVIDERS,
    build_api_url,
    build_careers_url,
)
from packages.infrastructure.db.repositories import CompanySourceRepository
from packages.infrastructure.db.session import get_session


BOARDS_FILE = Path(__file__).parent.parent / "configs" / "company_boards.yaml"

_SOURCE_TO_PROVIDER = {
    "greenhouse": "greenhouse",
    "lever": "lever",
    "ashby": "ashby",
    "workday": "workday",
}


def _extract_token(entry: dict, source: str, company: str) -> str | None:
    if source in ("greenhouse", "lever", "ashby"):
        return entry.get("board_token")
    if source == "workday":
        return entry.get("tenant") or entry.get("host", "").split(".")[0]
    return None


@click.command()
@click.option("--dry-run", is_flag=True, help="Print what would be imported without writing to DB")
def main(dry_run: bool) -> None:
    if not BOARDS_FILE.exists():
        click.echo(f"ERROR: {BOARDS_FILE} not found")
        sys.exit(1)

    data = yaml.safe_load(BOARDS_FILE.read_text())
    if not isinstance(data, dict):
        click.echo("ERROR: unexpected YAML structure")
        sys.exit(1)

    entries = []
    for company, info in data.items():
        if not isinstance(info, dict):
            continue
        source = info.get("source", "")
        provider = _SOURCE_TO_PROVIDER.get(source)
        if not provider:
            click.echo(f"  SKIP {company}: unsupported source '{source}'")
            continue

        token = _extract_token(info, source, company)
        if not token:
            click.echo(f"  SKIP {company}: no token found")
            continue

        status_map = {"active": "verified", "best_effort": "discovered", "hard_source": "blocked"}
        status = status_map.get(info.get("status", ""), "discovered")

        api_url = build_api_url(provider, token) if provider in ATS_PROVIDERS else None
        careers_url = build_careers_url(provider, token) if provider in ATS_PROVIDERS else None

        if provider == "workday":
            host = info.get("host", "")
            api_url = f"https://{host}" if host else None
            careers_url = api_url

        verified_at = None
        if info.get("verified_at"):
            try:
                verified_at = datetime.fromisoformat(str(info["verified_at"])).replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                pass

        entries.append({
            "company_name": company.replace("_", " ").title(),
            "ats_provider": provider,
            "board_token": token,
            "board_api_url": api_url,
            "board_careers_url": careers_url,
            "status": status,
            "last_verified_at": verified_at,
            "metadata_json": {"migrated_from": "company_boards.yaml", "notes": info.get("notes")},
        })

    click.echo(f"\nFound {len(entries)} boards to import.\n")

    if dry_run:
        for e in entries:
            click.echo(f"  {e['ats_provider']}/{e['board_token']} → {e['company_name']} ({e['status']})")
        click.echo("\n(dry-run mode — no DB writes)")
        return

    with get_session() as session:
        repo = CompanySourceRepository(session)
        created = skipped = 0
        for e in entries:
            existing = repo.get_by_board(e["ats_provider"], e["board_token"])
            if existing:
                click.echo(f"  EXISTS {e['ats_provider']}/{e['board_token']}")
                skipped += 1
                continue
            repo.create(**e)
            click.echo(f"  CREATED {e['ats_provider']}/{e['board_token']} → {e['company_name']}")
            created += 1
        session.commit()

    click.echo(f"\nDone: {created} created, {skipped} skipped.")


if __name__ == "__main__":
    main()

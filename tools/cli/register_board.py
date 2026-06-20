#!/usr/bin/env python3
"""
career-register-board — Register a new company ATS board in configs/company_boards.yaml.

Usage:
    career-register-board --name "Acme Corp" --ats greenhouse --url https://boards.greenhouse.io/acme

This is the ONLY sanctioned way to write configs/company_boards.yaml (per AGENTS.md).
Agents must not modify this file directly.
"""

from __future__ import annotations

import sys
from pathlib import Path

import click
import yaml


BOARDS_FILE = Path(__file__).parent.parent.parent / "configs" / "company_boards.yaml"

VALID_ATS = {
    "greenhouse",
    "lever",
    "ashby",
    "workday",
    "icims",
    "smartrecruiters",
    "jobvite",
    "taleo",
    "bamboohr",
    "other",
}


@click.command()
@click.option("--name", required=True, help="Company name")
@click.option(
    "--ats",
    required=True,
    type=click.Choice(list(VALID_ATS), case_sensitive=False),
    help="ATS platform type",
)
@click.option("--url", required=True, help="Job board URL")
@click.option("--status", default="active", show_default=True, help="Board status (active|paused)")
@click.option("--notes", default="", help="Optional notes")
def main(name: str, ats: str, url: str, status: str, notes: str) -> None:
    """Register a company ATS board in configs/company_boards.yaml."""
    if not BOARDS_FILE.exists():
        data: dict = {"boards": []}
    else:
        try:
            data = yaml.safe_load(BOARDS_FILE.read_text()) or {"boards": []}
        except Exception as exc:
            click.echo(f"ERROR: could not read {BOARDS_FILE}: {exc}", err=True)
            sys.exit(1)

    boards = data.get("boards", [])

    # Check for duplicate URL
    for board in boards:
        if board.get("url") == url:
            click.echo(f"Board with URL {url!r} already registered (company={board.get('name')})")
            sys.exit(0)

    entry = {
        "name": name,
        "ats": ats.lower(),
        "url": url,
        "status": status,
    }
    if notes:
        entry["notes"] = notes

    boards.append(entry)
    data["boards"] = boards

    BOARDS_FILE.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True))
    click.echo(f"Registered: {name} ({ats}) → {url}")


if __name__ == "__main__":
    main()

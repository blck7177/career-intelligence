#!/usr/bin/env python3
"""Migration guard — the thing no test and no CI job has ever done: actually run
the migrations.

Until now the schema was only ever created by `Base.metadata.create_all()` in the
test fixtures, so the migration chain was unverified by construction. A V1 review
proved it concretely: deleting a migration file left the suite at 545 passed.

Three checks, each aimed at a failure this repo can really produce:

  1. UPGRADE  — `alembic upgrade head` against an EMPTY database. Catches a
     broken chain (a deleted revision that others point at), a second head from
     two branches adding migrations in parallel, and any migration that only
     works against a database that already has data in it.

  2. COVERAGE — every table and column the models declare exists in the migrated
     database. This is the one that catches the common mistake: a column added to
     models.py with no migration written for it. The test suite cannot catch it,
     because create_all() builds the schema FROM the models — the two agree by
     definition.

  3. ROUND TRIP — downgrade the newest revision and re-upgrade. Catches a
     downgrade() that was never run. Done by hand every wave until now, which
     means it was one forgotten step away from not being done.

Deliberately NOT a full `alembic check` (metadata vs database in BOTH
directions): the repo carries ~30 pre-existing drift items — an orphaned
`candidate_story_bank` table from a deleted feature, indexes the models never
declared, a JSONB/JSON and a VARCHAR(64)/String(128) mismatch. Gating on that
today would mean a job that is red on arrival, and a red-on-arrival job teaches
people to ignore it. Check 2 is the half that can be enforced now: it fails only
on drift THIS change introduced, and tolerates the historical kind. Cleaning up
the rest is its own piece of work.

Usage: DATABASE_URL=postgresql://... python scripts/check-migrations.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def run(*args: str) -> None:
    """Run an alembic subcommand, echoing it; abort the guard on failure."""
    print(f"\n$ alembic {' '.join(args)}", flush=True)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args], cwd=REPO_ROOT, text=True
    )
    if result.returncode != 0:
        sys.exit(f"FAILED: alembic {' '.join(args)} exited {result.returncode}")


def main() -> int:
    url = os.environ.get("DATABASE_URL")
    if not url:
        # env.py falls back to the PRODUCTION database name when DATABASE_URL is
        # unset. A guard that silently migrates production is worse than no guard.
        return int(bool(sys.exit("DATABASE_URL must be set (env.py's fallback points at the production database)")))
    if url.startswith("sqlite"):
        return int(bool(sys.exit("This guard must run against postgres — sqlite would prove nothing about the real schema")))

    print(f"migration guard against {url.rsplit('@', 1)[-1]}")

    # --- 1. the whole chain, from nothing -----------------------------------
    run("upgrade", "head")

    # --- 2. models ⊆ migrated schema ----------------------------------------
    from sqlalchemy import create_engine, inspect

    from packages.infrastructure.db.models import Base

    engine = create_engine(url)
    inspector = inspect(engine)
    db_tables = set(inspector.get_table_names())

    missing: list[str] = []
    for name, table in Base.metadata.tables.items():
        if name not in db_tables:
            missing.append(f"table {name}")
            continue
        present = {c["name"] for c in inspector.get_columns(name)}
        missing.extend(
            f"column {name}.{c.name}" for c in table.columns if c.name not in present
        )

    print(f"\ncoverage: {len(Base.metadata.tables)} model tables vs {len(db_tables)} in the migrated database")
    if missing:
        print("\nFAILED: declared in models.py, absent from the migrated schema:")
        for item in missing:
            print(f"  - {item}")
        print(
            "\nA migration is missing. The test suite cannot see this: its fixtures\n"
            "build the schema with create_all() straight from these same models."
        )
        return 1
    print("  every model table and column exists in the migrated schema")

    # --- 3. the newest revision's downgrade actually runs --------------------
    run("downgrade", "-1")
    run("upgrade", "head")
    print("\nmigration guard passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

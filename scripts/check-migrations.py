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

  2. DRIFT — `alembic check`: the models and the migrated database must describe
     the same schema, in BOTH directions. Catches the common mistake (a column
     added to models.py with no migration for it), which the test suite cannot
     catch because create_all() builds the schema FROM the models — the two
     agree by definition. It also catches the opposite: a migration that adds an
     index or constraint nobody declares, which then survives only as long as
     nobody regenerates.

  3. ROUND TRIP — downgrade the newest revision and re-upgrade. Catches a
     downgrade() that was never run. Done by hand every wave until now, which
     means it was one forgotten step away from not being done.

Check 2 was deliberately weaker when this script was written: the repo carried 26
pre-existing drift items, so `alembic check` was red on arrival, and a
red-on-arrival check is one people learn to scroll past. Those were fixed
(models.py caught up to the deployed schema; the orphaned candidate_story_bank
table was dropped), so the real gate is now affordable.

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

    # --- 2. models and migrated schema agree, both directions ----------------
    print("\n$ alembic check", flush=True)
    check = subprocess.run(
        [sys.executable, "-m", "alembic", "check"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    print(check.stdout or check.stderr, end="")
    if check.returncode != 0:
        print(
            "\nFAILED: models.py and the migration chain describe different schemas.\n"
            "\n"
            "If you added or changed a column: the migration for it is missing. No\n"
            "test can tell you that — the fixtures build their schema with\n"
            "create_all() straight from these same models, so the two always agree\n"
            "there. Write the migration.\n"
            "\n"
            "If the difference is an index or constraint the database has and the\n"
            "models do not: add the declaration rather than generating a drop. The\n"
            "object is deployed; the declaration is what is missing."
        )
        return 1

    # --- 3. the newest revision's downgrade actually runs --------------------
    run("downgrade", "-1")
    run("upgrade", "head")
    print("\nmigration guard passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

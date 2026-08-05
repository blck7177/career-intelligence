"""re-normalize canonical_urls after `iisn` joined the strip-list

normalize_job_url learned one more tracking param (`iisn`, the companion of
`iis`: ?iis=Job+Boards&iisn=Indeed on higher.gs.com). Stored URLs must be
backfilled whenever that function changes, or dedup silently breaks: an old row
keeps the param, a re-import normalizes it away, and the canonical_url lookup
misses — one posting, two rows.

Same collision policy as l0m1n2o3p4q5: both rows referenced -> raise for a
human; one referenced -> references win; neither -> a real title outranks a
bare-numeric-id husk.

Revision ID: m1n2o3p4q5r6
Revises: l0m1n2o3p4q5
Create Date: 2026-08-05
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

from packages.domain.agent_jobs.url_normalize import normalize_job_url

revision = "m1n2o3p4q5r6"
down_revision = "l0m1n2o3p4q5"
branch_labels = None
depends_on = None

_REF_TABLES = (
    "job_favorites",
    "fit_reports",
    "job_reports",
    "job_not_interested",
    "job_applications",
)


def _ref_count(conn, job_id) -> int:
    return sum(
        conn.execute(
            text(f"SELECT count(*) FROM {table} WHERE job_id = :i"), {"i": job_id}
        ).scalar()
        for table in _REF_TABLES
    )


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(text("SELECT id, canonical_url, title FROM jobs")).fetchall()
    for row in rows:
        norm = normalize_job_url(row.canonical_url)
        if norm == row.canonical_url:
            continue
        dup = conn.execute(
            text("SELECT id, title FROM jobs WHERE canonical_url = :u AND id <> :i"),
            {"u": norm, "i": row.id},
        ).fetchone()
        if dup is None:
            conn.execute(
                text("UPDATE jobs SET canonical_url = :u WHERE id = :i"),
                {"u": norm, "i": row.id},
            )
            continue

        row_refs = _ref_count(conn, row.id)
        dup_refs = _ref_count(conn, dup.id)
        if row_refs and dup_refs:
            raise RuntimeError(
                f"canonical_url dedup: rows {row.id} and {dup.id} are the same "
                f"posting ({norm}) and both carry references "
                f"({row_refs} vs {dup_refs}); merge manually before re-running."
            )
        if row_refs != dup_refs:
            keep, drop = (row, dup) if row_refs else (dup, row)
        else:
            row_husk = (row.title or "").strip().isdigit()
            dup_husk = (dup.title or "").strip().isdigit()
            keep, drop = (row, dup) if (dup_husk and not row_husk) else (dup, row)

        conn.execute(text("DELETE FROM jobs WHERE id = :i"), {"i": drop.id})
        conn.execute(
            text("UPDATE jobs SET canonical_url = :u WHERE id = :i"),
            {"u": norm, "i": keep.id},
        )


def downgrade() -> None:
    # Lossy: stripped params and dropped duplicate rows are gone.
    pass

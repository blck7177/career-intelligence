"""normalize existing canonical_urls (strip tracking params, dedup)

One-time backfill so stored canonical_urls match what normalize_job_url now
produces at ingest. Strips tracking/referrer query params (keeping job-id
params like gh_jid/jk), lowercases host, drops fragments. Rows whose normalized
form collides with another row are duplicates of the same posting discovered
before normalization existed — the pre-existing row is kept and the duplicate
dropped, but only when nothing references it (otherwise the migration raises so
a human merges rather than orphaning data).

Revision ID: z7a8b9c0d1e2
Revises: y6z7a8b9c0d1
Create Date: 2026-07-17
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

from packages.domain.agent_jobs.url_normalize import normalize_job_url

revision = "z7a8b9c0d1e2"
down_revision = "y6z7a8b9c0d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(text("SELECT id, canonical_url FROM jobs")).fetchall()
    for row in rows:
        norm = normalize_job_url(row.canonical_url)
        if norm == row.canonical_url:
            continue
        dup = conn.execute(
            text("SELECT id FROM jobs WHERE canonical_url = :u AND id <> :i"),
            {"u": norm, "i": row.id},
        ).fetchone()
        if dup is None:
            conn.execute(
                text("UPDATE jobs SET canonical_url = :u WHERE id = :i"),
                {"u": norm, "i": row.id},
            )
            continue
        refs = conn.execute(
            text(
                "SELECT (SELECT count(*) FROM job_favorites WHERE job_id = :i)"
                " + (SELECT count(*) FROM fit_reports WHERE job_id = :i)"
                " + (SELECT count(*) FROM job_reports WHERE job_id = :i)"
            ),
            {"i": row.id},
        ).scalar()
        if refs:
            raise RuntimeError(
                f"canonical_url dedup: row {row.id} normalizes to a value that "
                f"already exists on row {dup.id}, but it has {refs} reference(s); "
                "merge manually before re-running."
            )
        conn.execute(text("DELETE FROM jobs WHERE id = :i"), {"i": row.id})


def downgrade() -> None:
    # Lossy: stripped tracking params and dropped duplicate rows are gone.
    pass

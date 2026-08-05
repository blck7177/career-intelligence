"""re-normalize canonical_urls (iis param, /careers/job/<id>-<slug>)

Backfill after normalize_job_url learned two new rules: strip the `iis`
referrer param (?iis=LinkedIn) and strip the title slug from eightfold-family
/careers/job/<id>-<slug> paths (the id is the identity, the slug varies by
referrer — proven by a production dup pair on careers.newyorklife.com).

Collision policy (extends z7a8b9c0d1e2): two rows collapsing to one
canonical_url are the same posting reached via different referrers, so exactly
one row survives —
  * both referenced        -> raise; a human merges rather than orphaning data
  * exactly one referenced -> keep it (references outrank everything)
  * neither referenced     -> keep the row whose title is not just the numeric
    job id (the bare-id fetch produced a husk row titled "39995361"; the slug
    row carries the real title). Tie -> keep the already-normalized row.
The surviving row takes the normalized canonical_url.

Revision ID: l0m1n2o3p4q5
Revises: k9l0m1n2o3p4
Create Date: 2026-08-05
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

from packages.domain.agent_jobs.url_normalize import normalize_job_url

revision = "l0m1n2o3p4q5"
down_revision = "k9l0m1n2o3p4"
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
    total = 0
    for table in _REF_TABLES:
        total += conn.execute(
            text(f"SELECT count(*) FROM {table} WHERE job_id = :i"), {"i": job_id}
        ).scalar()
    return total


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
            # Neither referenced: prefer the row with a real title over a
            # bare-numeric-id husk; tie goes to the already-normalized row.
            row_husk = (row.title or "").strip().isdigit()
            dup_husk = (dup.title or "").strip().isdigit()
            keep, drop = (row, dup) if (dup_husk and not row_husk) else (dup, row)

        conn.execute(text("DELETE FROM jobs WHERE id = :i"), {"i": drop.id})
        conn.execute(
            text("UPDATE jobs SET canonical_url = :u WHERE id = :i"),
            {"u": norm, "i": keep.id},
        )


def downgrade() -> None:
    # Lossy: stripped slugs/params and dropped duplicate rows are gone.
    pass

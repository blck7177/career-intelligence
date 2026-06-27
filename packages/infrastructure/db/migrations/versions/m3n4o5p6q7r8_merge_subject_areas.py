"""merge domain_experience + finance_domains into subject_areas

Revision ID: m3n4o5p6q7r8
Revises: l2m3n4o5p6q7
Create Date: 2026-06-25

Changes:
  - Add subject_areas (JSON, nullable)
  - Backfill: dedupe merge of domain_experience then finance_domains
  - Drop finance_domains, domain_experience
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "m3n4o5p6q7r8"
down_revision = "l2m3n4o5p6q7"
branch_labels = None
depends_on = None


def _merge_subject_areas(domain_experience, finance_domains) -> list[str] | None:
    merged: list[str] = []
    seen: set[str] = set()
    for source in (domain_experience or [], finance_domains or []):
        if not isinstance(source, list):
            continue
        for item in source:
            if not isinstance(item, str):
                continue
            value = item.strip()
            if not value or value in seen:
                continue
            seen.add(value)
            merged.append(value)
    return merged or None


def upgrade() -> None:
    op.add_column(
        "candidate_profiles",
        sa.Column("subject_areas", sa.JSON(), nullable=True),
    )

    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT id, domain_experience, finance_domains FROM candidate_profiles"
        )
    ).fetchall()

    for row in rows:
        subject_areas = _merge_subject_areas(row.domain_experience, row.finance_domains)
        conn.execute(
            sa.text(
                "UPDATE candidate_profiles SET subject_areas = CAST(:subject_areas AS JSON) WHERE id = :id"
            ),
            {
                "subject_areas": json.dumps(subject_areas) if subject_areas is not None else None,
                "id": row.id,
            },
        )

    op.drop_column("candidate_profiles", "finance_domains")
    op.drop_column("candidate_profiles", "domain_experience")


def downgrade() -> None:
    op.add_column(
        "candidate_profiles",
        sa.Column("domain_experience", sa.JSON(), nullable=True),
    )
    op.add_column(
        "candidate_profiles",
        sa.Column("finance_domains", sa.JSON(), nullable=True),
    )

    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, subject_areas FROM candidate_profiles")
    ).fetchall()

    for row in rows:
        domain_experience = row.subject_areas if isinstance(row.subject_areas, list) else None
        conn.execute(
            sa.text(
                "UPDATE candidate_profiles "
                "SET domain_experience = CAST(:domain_experience AS JSON), "
                "finance_domains = CAST(:finance_domains AS JSON) "
                "WHERE id = :id"
            ),
            {
                "domain_experience": json.dumps(domain_experience) if domain_experience is not None else None,
                "finance_domains": None,
                "id": row.id,
            },
        )

    op.drop_column("candidate_profiles", "subject_areas")

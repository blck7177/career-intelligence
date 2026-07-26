"""add dead_urls table

Negative cache / audit table for job-posting URLs confirmed dead on arrival
(HTTP 404/410 or a closed-posting page). DOA URLs are recorded here instead of
creating a zombie 'discovered' job row, and looked up to skip re-fetching the
same dead URL every discovery run.

Revision ID: a8b9c0d1e2f3
Revises: z7a8b9c0d1e2
Create Date: 2026-07-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a8b9c0d1e2f3"
down_revision = "z7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dead_urls",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("url_hash", sa.String(32), nullable=False),
        sa.Column("canonical_url", sa.String(2048), nullable=False),
        sa.Column("domain", sa.String(255), nullable=True),
        sa.Column("reason", sa.String(32), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("times_seen", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("discovered_run_id", sa.String(36), nullable=True),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("url_hash", name="uq_dead_urls_url_hash"),
    )
    op.create_index("ix_dead_urls_domain", "dead_urls", ["domain"])


def downgrade() -> None:
    op.drop_index("ix_dead_urls_domain", table_name="dead_urls")
    op.drop_table("dead_urls")

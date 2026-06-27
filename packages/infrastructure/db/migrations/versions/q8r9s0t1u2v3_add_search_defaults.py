"""add search_defaults JSON column to candidate_profiles

Revision ID: q8r9s0t1u2v3
Revises: p7q8r9s0t1u2
Create Date: 2026-06-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "q8r9s0t1u2v3"
down_revision = "p7q8r9s0t1u2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "candidate_profiles",
        sa.Column("search_defaults", sa.JSON, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("candidate_profiles", "search_defaults")

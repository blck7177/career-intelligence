"""Add source_provider to jobs; normalize source_type to category.

Revision ID: k1l2m3n4o5p6
Revises: j0k1l2m3n4o5
Create Date: 2026-06-24

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "k1l2m3n4o5p6"
down_revision = "j0k1l2m3n4o5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("source_provider", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "source_provider")

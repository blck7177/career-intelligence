"""add tier column to workspaces

Revision ID: y6z7a8b9c0d1
Revises: x5y6z7a8b9c0
Create Date: 2026-07-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "y6z7a8b9c0d1"
down_revision = "x5y6z7a8b9c0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column("tier", sa.String(20), nullable=False, server_default="new"),
    )


def downgrade() -> None:
    op.drop_column("workspaces", "tier")

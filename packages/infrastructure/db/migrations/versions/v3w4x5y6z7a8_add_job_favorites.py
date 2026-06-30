"""add job_favorites table

Revision ID: v3w4x5y6z7a8
Revises: u2v3w4x5y6z7
Create Date: 2026-06-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "v3w4x5y6z7a8"
down_revision = "u2v3w4x5y6z7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_favorites",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("workspace_id", "job_id", name="uq_job_favorites_workspace_job"),
    )
    op.create_index("ix_job_favorites_workspace_id", "job_favorites", ["workspace_id"])
    op.create_index("ix_job_favorites_job_id", "job_favorites", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_job_favorites_job_id")
    op.drop_index("ix_job_favorites_workspace_id")
    op.drop_table("job_favorites")

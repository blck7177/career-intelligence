"""add job_not_interested table

Revision ID: b9c0d1e2f3g4
Revises: a8b9c0d1e2f3
Create Date: 2026-07-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b9c0d1e2f3g4"
down_revision = "a8b9c0d1e2f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_not_interested",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("workspace_id", "job_id", name="uq_job_not_interested_workspace_job"),
    )
    op.create_index("ix_job_not_interested_workspace_id", "job_not_interested", ["workspace_id"])
    op.create_index("ix_job_not_interested_job_id", "job_not_interested", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_job_not_interested_job_id")
    op.drop_index("ix_job_not_interested_workspace_id")
    op.drop_table("job_not_interested")

"""add search_strategy_states table

Revision ID: n5o6p7q8r9s0
Revises: o6p7q8r9s0t1
Create Date: 2026-06-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "n5o6p7q8r9s0"
down_revision = "o6p7q8r9s0t1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "search_strategy_states",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("profile_id", sa.String(36), nullable=True),
        sa.Column("state_json", sa.JSON(), nullable=False),
        sa.Column("last_reflection_run_id", sa.String(36), nullable=True),
        sa.Column("last_reflection_task_id", sa.String(36), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_search_strategy_states_workspace_id",
        "search_strategy_states",
        ["workspace_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_search_strategy_states_workspace_id", "search_strategy_states")
    op.drop_table("search_strategy_states")

"""add company_sources table

Revision ID: t1u2v3w4x5y6
Revises: s0t1u2v3w4x5
Create Date: 2026-06-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "t1u2v3w4x5y6"
down_revision = "s0t1u2v3w4x5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "company_sources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=True),
        sa.Column("company_name", sa.String(255), nullable=False),
        sa.Column("ats_provider", sa.String(64), nullable=False),
        sa.Column("board_token", sa.String(255), nullable=False),
        sa.Column("board_api_url", sa.String(2048), nullable=True),
        sa.Column("board_careers_url", sa.String(2048), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="discovered"),
        sa.Column("discovered_run_id", sa.String(36), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("job_count_last_sync", sa.Integer, nullable=False, server_default="0"),
        sa.Column("metadata_json", sa.JSON, nullable=True),
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
        sa.UniqueConstraint("ats_provider", "board_token", name="uq_company_sources_provider_token"),
    )
    op.create_index("ix_company_sources_status", "company_sources", ["status"])


def downgrade() -> None:
    op.drop_index("ix_company_sources_status")
    op.drop_table("company_sources")

"""add candidate_story_bank table

Revision ID: w4x5y6z7a8b9
Revises: v3w4x5y6z7a8
Create Date: 2026-07-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "w4x5y6z7a8b9"
down_revision = "v3w4x5y6z7a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "candidate_story_bank",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("candidate_profiles.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("workspace_id", sa.String(36), nullable=False, index=True),
        sa.Column("run_id", sa.String(36), nullable=True),
        sa.Column("experience_ref", sa.String(50), nullable=False),
        sa.Column("story_id", sa.String(100), nullable=False),
        sa.Column("workstream_title", sa.String(500), nullable=False),
        sa.Column("bullets_covered", sa.JSON, nullable=True),
        sa.Column("narrative", sa.Text, nullable=True),
        sa.Column("workflow", sa.JSON, nullable=True),
        sa.Column("evidence_items", sa.JSON, nullable=True),
        sa.Column("candidate_questions", sa.JSON, nullable=True),
        sa.Column("do_not_claim", sa.JSON, nullable=True),
        sa.Column("research_basis", sa.JSON, nullable=True),
        sa.Column("user_edited_at", sa.DateTime(timezone=True), nullable=True),
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


def downgrade() -> None:
    op.drop_table("candidate_story_bank")

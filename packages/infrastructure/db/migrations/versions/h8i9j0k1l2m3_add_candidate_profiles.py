"""add candidate_profiles table

Revision ID: h8i9j0k1l2m3
Revises: g7h8i9j0k1l2
Create Date: 2026-06-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "h8i9j0k1l2m3"
down_revision = "g7h8i9j0k1l2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "candidate_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False, unique=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("experience_summary", sa.Text(), nullable=True),
        sa.Column("education_summary", sa.Text(), nullable=True),
        sa.Column("technical_skills", sa.JSON(), nullable=True),
        sa.Column("domain_areas", sa.JSON(), nullable=True),
        sa.Column("preferences_json", sa.JSON(), nullable=True),
        sa.Column("years_of_experience", sa.Integer(), nullable=True),
        sa.Column("profile_hash", sa.String(32), nullable=False, server_default="empty"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_candidate_profiles_workspace_id", "candidate_profiles", ["workspace_id"])


def downgrade() -> None:
    op.drop_index("ix_candidate_profiles_workspace_id", "candidate_profiles")
    op.drop_table("candidate_profiles")

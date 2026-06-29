"""add structured_resume_json to candidate_profiles

Revision ID: u2v3w4x5y6z7
Revises: t1u2v3w4x5y6
Create Date: 2026-06-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "u2v3w4x5y6z7"
down_revision = "t1u2v3w4x5y6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "candidate_profiles",
        sa.Column("structured_resume_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("candidate_profiles", "structured_resume_json")

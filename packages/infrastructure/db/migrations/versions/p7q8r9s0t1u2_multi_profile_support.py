"""multi-profile support: drop unique constraint, add label column

Revision ID: p7q8r9s0t1u2
Revises: n5o6p7q8r9s0
Create Date: 2026-06-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "p7q8r9s0t1u2"
down_revision = "n5o6p7q8r9s0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_candidate_profiles_workspace_id", table_name="candidate_profiles")
    op.drop_constraint(
        "candidate_profiles_workspace_id_key", "candidate_profiles", type_="unique"
    )
    op.add_column(
        "candidate_profiles",
        sa.Column("label", sa.String(100), nullable=False, server_default=""),
    )
    op.create_index(
        "ix_candidate_profiles_workspace_id",
        "candidate_profiles",
        ["workspace_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_candidate_profiles_workspace_id", table_name="candidate_profiles")
    op.drop_column("candidate_profiles", "label")
    op.create_index(
        "ix_candidate_profiles_workspace_id",
        "candidate_profiles",
        ["workspace_id"],
        unique=True,
    )
    op.create_unique_constraint(
        "candidate_profiles_workspace_id_key", "candidate_profiles", ["workspace_id"]
    )

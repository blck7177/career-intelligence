"""unify candidate_profiles — rename domain_areas/years_of_experience, add fit-report columns

Revision ID: i9j0k1l2m3n4
Revises: h8i9j0k1l2m3
Create Date: 2026-06-23

Changes:
  - Rename domain_areas       → domain_experience
  - Rename years_of_experience → years_experience
  - Add finance_domains  (JSON, nullable)
  - Add tools            (JSON, nullable)
  - Add representative_projects (JSON, nullable)
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "i9j0k1l2m3n4"
down_revision = "h8i9j0k1l2m3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Rename domain_areas → domain_experience
    op.alter_column(
        "candidate_profiles",
        "domain_areas",
        new_column_name="domain_experience",
        existing_type=sa.JSON(),
        nullable=True,
    )

    # Rename years_of_experience → years_experience
    op.alter_column(
        "candidate_profiles",
        "years_of_experience",
        new_column_name="years_experience",
        existing_type=sa.Integer(),
        nullable=True,
    )

    # Add new FitReport columns
    op.add_column(
        "candidate_profiles",
        sa.Column("finance_domains", sa.JSON(), nullable=True),
    )
    op.add_column(
        "candidate_profiles",
        sa.Column("tools", sa.JSON(), nullable=True),
    )
    op.add_column(
        "candidate_profiles",
        sa.Column("representative_projects", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("candidate_profiles", "representative_projects")
    op.drop_column("candidate_profiles", "tools")
    op.drop_column("candidate_profiles", "finance_domains")

    op.alter_column(
        "candidate_profiles",
        "years_experience",
        new_column_name="years_of_experience",
        existing_type=sa.Integer(),
        nullable=True,
    )

    op.alter_column(
        "candidate_profiles",
        "domain_experience",
        new_column_name="domain_areas",
        existing_type=sa.JSON(),
        nullable=True,
    )

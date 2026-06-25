"""drop candidate_profiles.preferences_json

Revision ID: l2m3n4o5p6q7
Revises: k1l2m3n4o5p6
Create Date: 2026-06-25

Job-search preferences belong in JobDiscoveryFrontendInput.soft_preferences (per-run),
not in CandidateProfile.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "l2m3n4o5p6q7"
down_revision = "k1l2m3n4o5p6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("candidate_profiles", "preferences_json")


def downgrade() -> None:
    op.add_column(
        "candidate_profiles",
        sa.Column("preferences_json", sa.JSON(), nullable=True),
    )

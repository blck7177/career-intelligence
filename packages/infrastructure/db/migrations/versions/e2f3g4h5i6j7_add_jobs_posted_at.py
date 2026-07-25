"""add jobs.posted_at

The employer's original posting date, captured from the ATS board API when it
exposes one (Greenhouse first_published/updated_at, Lever createdAt, Ashby
publishedAt). Nullable, NOT backfilled for existing rows — their posting date is
genuinely unknown, so they keep falling back to "seen Xd" (created_at).

Revision ID: e2f3g4h5i6j7
Revises: d1e2f3g4h5i6
Create Date: 2026-07-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e2f3g4h5i6j7"
down_revision = "d1e2f3g4h5i6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("jobs", "posted_at")

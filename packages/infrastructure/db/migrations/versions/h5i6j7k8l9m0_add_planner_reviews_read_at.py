"""add planner_reviews.read_at

When the user first opened this weekly review. NULL means unread, which is what
the Plan view's banner keys off — a review nobody has seen yet is the whole
reason the weekly beat is worth running, and until now it landed silently at the
bottom of a scroll container.

Nullable and NOT backfilled, unlike snooze_count: "already read" is not a fact
we possess about existing rows. Marking them read would hide a review the user
genuinely never saw; leaving them NULL surfaces it once, which is the honest
failure direction.

Revision ID: h5i6j7k8l9m0
Revises: g4h5i6j7k8l9
Create Date: 2026-07-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "h5i6j7k8l9m0"
down_revision = "g4h5i6j7k8l9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "planner_reviews",
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("planner_reviews", "read_at")

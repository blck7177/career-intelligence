"""add application_actions.scheduled_at

When a to-do is planned to START, as a UTC instant. The planner has always known
WHICH DAY a to-do is due (due_at, encoded as local midnight) but never what time
of day it was meant to happen, so "what does Thursday actually look like" had no
data behind it. Duration is not stored alongside it: est_minutes already carries
that, and a second copy would be free to disagree with the number the capacity
bar and the weekly review are totalling.

Nullable and NOT backfilled, and the two states are meaningfully different: NULL
means "not placed on the calendar yet" — that is exactly the unscheduled tray
the week view is built around — while a value means the user put it somewhere on
purpose. Backfilling anything here would invent intent the user never expressed.

Indexed because the week grid's query is a range scan over it, and the table had
no index on any time column at all (not even due_at).

Revision ID: k9l0m1n2o3p4
Revises: j8k9l0m1n2o3
Create Date: 2026-08-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "k9l0m1n2o3p4"
down_revision = "j8k9l0m1n2o3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "application_actions",
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_application_actions_scheduled_at", "application_actions", ["scheduled_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_application_actions_scheduled_at", table_name="application_actions")
    op.drop_column("application_actions", "scheduled_at")

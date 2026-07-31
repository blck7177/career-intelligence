"""add planner_day_logs

One row per (workspace, local day): what the user committed to that morning and
what they actually closed the day with. It is the only place the planner keeps a
record of intent as opposed to outcome — every other table records what
happened, so "did I plan realistically?" has had no data behind it.

committed_est and done_est are both stored rather than derived. done_est could be
recomputed from completed_at any time, but committed_est cannot: it is a snapshot
of a decision made at a moment, against a to-do list that changes all day. Losing
it would leave the weekly comparison with only one of its two numbers.

Nullable on purpose, and not backfilled. A day with no row is a day the ritual
was never run, which is different from a day committed to nothing; and
committed_est stays NULL until the morning ritual, done_est until the evening
one, so the pair also encodes how far through the day's ritual you got.

Revision ID: j8k9l0m1n2o3
Revises: i7j8k9l0m1n2
Create Date: 2026-07-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "j8k9l0m1n2o3"
down_revision = "i7j8k9l0m1n2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "planner_day_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id"),
            nullable=False,
            index=True,
        ),
        # The calendar day in settings.timezone — same day boundary the rules
        # engine and the Today query use. Never a UTC date.
        sa.Column("local_date", sa.Date, nullable=False),
        sa.Column("committed_est", sa.Integer, nullable=True),
        sa.Column("done_est", sa.Integer, nullable=True),
        sa.Column("reflection", sa.Text, nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
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
    op.create_unique_constraint(
        "uq_planner_day_logs_workspace_date",
        "planner_day_logs",
        ["workspace_id", "local_date"],
    )


def downgrade() -> None:
    op.drop_table("planner_day_logs")

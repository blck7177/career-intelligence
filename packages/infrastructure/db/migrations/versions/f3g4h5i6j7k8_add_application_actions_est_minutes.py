"""add application_actions.est_minutes

The planner's effort estimate for one to-do, in minutes. The rules engine emits
a per-type default (follow-up 15, thank-you 15, prep 30, apply 60, refill 15) so
the Today view can total the day against the workspace's daily cap. Nullable and
NOT backfilled: existing rows predate the estimate and manual rows may omit it,
so every consumer falls back to a per-type default rather than treating NULL as
zero.

Revision ID: f3g4h5i6j7k8
Revises: e2f3g4h5i6j7
Create Date: 2026-07-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f3g4h5i6j7k8"
down_revision = "e2f3g4h5i6j7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "application_actions",
        sa.Column("est_minutes", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("application_actions", "est_minutes")

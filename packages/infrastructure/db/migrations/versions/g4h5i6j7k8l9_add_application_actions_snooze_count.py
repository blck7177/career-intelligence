"""add application_actions.snooze_count

How many times a to-do has been pushed to a later day. The Today view surfaces
it once it climbs ("3rd time deferred") so a repeatedly-postponed item reads as
a decision to make rather than a line that quietly reappears forever.

NOT NULL with a 0 default: unlike est_minutes, "never deferred" is a known fact
about every existing row, so backfilling it is honest rather than invented.

Revision ID: g4h5i6j7k8l9
Revises: f3g4h5i6j7k8
Create Date: 2026-07-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "g4h5i6j7k8l9"
down_revision = "f3g4h5i6j7k8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "application_actions",
        sa.Column("snooze_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("application_actions", "snooze_count")

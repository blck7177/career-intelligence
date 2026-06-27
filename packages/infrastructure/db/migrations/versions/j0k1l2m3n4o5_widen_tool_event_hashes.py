"""widen agent_tool_events input_hash/output_hash to text

Revision ID: j0k1l2m3n4o5
Revises: i9j0k1l2m3n4
Create Date: 2026-06-24

Changes:
  - Alter input_hash  varchar(64) → text (sha256: prefix makes values 71+ chars)
  - Alter output_hash varchar(64) → text
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "j0k1l2m3n4o5"
down_revision = "i9j0k1l2m3n4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "agent_tool_events",
        "input_hash",
        existing_type=sa.String(64),
        type_=sa.Text(),
        nullable=True,
    )
    op.alter_column(
        "agent_tool_events",
        "output_hash",
        existing_type=sa.String(64),
        type_=sa.Text(),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "agent_tool_events",
        "output_hash",
        existing_type=sa.Text(),
        type_=sa.String(64),
        nullable=True,
    )
    op.alter_column(
        "agent_tool_events",
        "input_hash",
        existing_type=sa.Text(),
        type_=sa.String(64),
        nullable=True,
    )

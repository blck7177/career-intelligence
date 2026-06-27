"""add_signed_ledger_fields

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-06-22

Adds signed-ledger columns to agent_tool_events:
  event_id        — platform-generated "tevt_<uuid4>" (unique, nullable for old rows)
  sequence        — 1-based within invocation
  prev_event_hash — sha256 of previous event in chain (NULL for first event)
  event_hash      — sha256 of canonical event JSON (excluding event_hash/signature)
  signature       — HMAC-SHA256(TOOL_LEDGER_SIGNING_KEY, event_hash)
  raw_event_json  — full ToolLedgerEvent as JSONB for audit/replay

Existing rows will have NULL for all new columns (acceptable — no production data).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_tool_events",
        sa.Column("event_id", sa.Text(), nullable=True, unique=True),
    )
    op.add_column(
        "agent_tool_events",
        sa.Column("sequence", sa.Integer(), nullable=True),
    )
    op.add_column(
        "agent_tool_events",
        sa.Column("prev_event_hash", sa.Text(), nullable=True),
    )
    op.add_column(
        "agent_tool_events",
        sa.Column("event_hash", sa.Text(), nullable=True),
    )
    op.add_column(
        "agent_tool_events",
        sa.Column("signature", sa.Text(), nullable=True),
    )
    op.add_column(
        "agent_tool_events",
        sa.Column("raw_event_json", JSONB(), nullable=True),
    )

    op.create_index(
        "ix_agent_tool_events_event_id",
        "agent_tool_events",
        ["event_id"],
        unique=True,
        postgresql_where=sa.text("event_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_agent_tool_events_event_id", table_name="agent_tool_events")
    op.drop_column("agent_tool_events", "raw_event_json")
    op.drop_column("agent_tool_events", "signature")
    op.drop_column("agent_tool_events", "event_hash")
    op.drop_column("agent_tool_events", "prev_event_hash")
    op.drop_column("agent_tool_events", "sequence")
    op.drop_column("agent_tool_events", "event_id")

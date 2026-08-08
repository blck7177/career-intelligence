"""add application_events.event_at

When the thing an event describes HAPPENS, as a UTC instant — as opposed to
created_at, which is when it was logged. The two are uncorrelated: an interview
booked weeks ahead is an old row pointing at a future date. Until now that
instant lived only in payload_json["at"], so planner-week had to load every
interview_scheduled row in the workspace and filter by date in Python (JSON
predicates aren't portable to the SQLite used by tests). Calendar sync (W-δ)
reads the same column instead of parsing payloads.

Nullable: most event kinds (notes, status changes) have no such instant, and
NULL is exactly "nothing to place on a calendar".

Backfilled from payload_json->>'at' for existing interview_scheduled rows.
Values were written by datetime.isoformat() so they parse cleanly, but the cast
is wrapped in a per-row exception guard anyway — one hand-edited or corrupt
string must not abort the migration, it should just leave that row NULL (the
read path already skips interviews it can't date). Naive strings are read as
UTC to match the API's read path (`at.replace(tzinfo=timezone.utc)`).

The composite index (workspace_id, event_type, event_at) serves the only query
shape that exists: "this workspace's interviews inside this date range".
payload_json["at"] is kept on interview rows for backward compatibility.

Revision ID: n2o3p4q5r6s7
Revises: m1n2o3p4q5r6
Create Date: 2026-08-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "n2o3p4q5r6s7"
down_revision = "m1n2o3p4q5r6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "application_events",
        sa.Column("event_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_application_events_ws_type_at",
        "application_events",
        ["workspace_id", "event_type", "event_at"],
    )
    op.execute("SET LOCAL TIME ZONE 'UTC'")
    op.execute(
        """
        CREATE FUNCTION pg_temp.safe_timestamptz(t text) RETURNS timestamptz AS $$
        BEGIN
            RETURN t::timestamptz;
        EXCEPTION WHEN OTHERS THEN
            RETURN NULL;
        END $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        UPDATE application_events
        SET event_at = pg_temp.safe_timestamptz(payload_json->>'at')
        WHERE event_type = 'interview_scheduled'
          AND payload_json->>'at' IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_application_events_ws_type_at", table_name="application_events")
    op.drop_column("application_events", "event_at")

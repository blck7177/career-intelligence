"""add planner_reviews table

The weekly review (Wave 5): one row per (workspace, ISO-week) holding the
deterministic aggregate (stats_json) and an optional LLM narrative (narrative_md,
NULL when generation degraded to the pure-number template). Written by the weekly
Celery beat; read by the Plan view's Review zone.

Revision ID: d1e2f3g4h5i6
Revises: c0d1e2f3g4h5
Create Date: 2026-07-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d1e2f3g4h5i6"
down_revision = "c0d1e2f3g4h5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "planner_reviews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False
        ),
        # Monday (00:00) of the reviewed week, in the workspace's settings.timezone.
        sa.Column("week_start", sa.Date(), nullable=False),
        # Deterministic aggregate (WeeklyReviewStats) — the numbers the card and
        # the LLM narrative are both derived from.
        sa.Column("stats_json", sa.JSON, nullable=False),
        # LLM summary; NULL when generation degraded to the number-only template.
        sa.Column("narrative_md", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        # One review per (workspace, week) — re-running the beat upserts in place.
        sa.UniqueConstraint(
            "workspace_id", "week_start", name="uq_planner_reviews_workspace_week"
        ),
    )
    op.create_index(
        "ix_planner_reviews_workspace_id", "planner_reviews", ["workspace_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_planner_reviews_workspace_id", table_name="planner_reviews")
    op.drop_table("planner_reviews")

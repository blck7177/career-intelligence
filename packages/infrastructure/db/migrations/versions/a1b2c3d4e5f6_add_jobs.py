"""add_jobs

Revision ID: a1b2c3d4e5f6
Revises: 60f9c9c4f2f9
Create Date: 2026-06-22

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a1b2c3d4e5f6"
down_revision = "60f9c9c4f2f9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("canonical_url", sa.String(2048), nullable=False, unique=True),
        sa.Column("source_url", sa.String(2048), nullable=False),
        sa.Column("source_type", sa.String(64), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("company", sa.String(255), nullable=False),
        sa.Column("location", sa.String(255), nullable=True),
        sa.Column("jd_text", sa.Text, nullable=False),
        sa.Column("jd_hash", sa.String(32), nullable=False),
        sa.Column("raw_payload_json", sa.JSON, nullable=True),
        sa.Column(
            "status",
            sa.Enum("discovered", "reportable", "invalid", "stale", name="job_status"),
            nullable=False,
            server_default="discovered",
        ),
        sa.Column("discovered_run_id", sa.String(36), nullable=True),
        sa.Column("discovered_task_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_jobs_company", "jobs", ["company"])
    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_index("ix_jobs_jd_hash", "jobs", ["jd_hash"])


def downgrade() -> None:
    op.drop_table("jobs")
    op.execute("DROP TYPE IF EXISTS job_status")

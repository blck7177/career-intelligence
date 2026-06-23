"""make_job_jd_nullable

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-06-22

Make jobs.jd_text and jobs.jd_hash nullable.

Rationale: discovery creates job records with status="discovered" before the
job description has been fetched.  The jd_text / jd_hash are populated by a
subsequent job_research task.  Forcing NOT NULL at insert time blocks the
candidate_pool → jobs pipeline that runs immediately after the validator gate.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("jobs", "jd_text", existing_type=sa.Text(), nullable=True)
    op.alter_column("jobs", "jd_hash", existing_type=sa.String(length=32), nullable=True)


def downgrade() -> None:
    # Set empty string on any NULLs before re-adding NOT NULL constraint
    op.execute("UPDATE jobs SET jd_text = '' WHERE jd_text IS NULL")
    op.execute("UPDATE jobs SET jd_hash = '' WHERE jd_hash IS NULL")
    op.alter_column("jobs", "jd_text", existing_type=sa.Text(), nullable=False)
    op.alter_column("jobs", "jd_hash", existing_type=sa.String(length=32), nullable=False)

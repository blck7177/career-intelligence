"""add_job_reports_fit_reports

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-22

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("jd_hash", sa.String(32), nullable=False),
        sa.Column("prompt_version", sa.String(32), nullable=False),
        sa.Column("analysis_version", sa.String(32), nullable=False, server_default="1.0"),
        sa.Column("used_research", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("research_artifact_id", sa.String(36), nullable=True),
        sa.Column("research_bundle_hash", sa.String(32), nullable=False, server_default="none"),
        sa.Column(
            "status",
            sa.Enum("active", "superseded", "failed", name="job_report_status"),
            nullable=False,
            server_default="active",
        ),
        sa.Column("narrative_artifact_id", sa.String(36), nullable=True),
        sa.Column("structured_artifact_id", sa.String(36), nullable=True),
        sa.Column("structured_json", sa.JSON, nullable=True),
        sa.Column("summary_json", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_job_reports_job_id", "job_reports", ["job_id"])
    op.create_index("ix_job_reports_status", "job_reports", ["status"])
    op.create_index("ix_job_reports_jd_hash", "job_reports", ["jd_hash"])

    op.create_table(
        "fit_reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("job_report_id", sa.String(36), sa.ForeignKey("job_reports.id"), nullable=False),
        sa.Column("candidate_profile_id", sa.String(36), nullable=True),
        sa.Column("profile_hash", sa.String(32), nullable=False),
        sa.Column("prompt_version", sa.String(32), nullable=False),
        sa.Column("overall_match_score", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "status",
            sa.Enum("active", "superseded", "failed", name="fit_report_status"),
            nullable=False,
            server_default="active",
        ),
        sa.Column("structured_artifact_id", sa.String(36), nullable=True),
        sa.Column("narrative_artifact_id", sa.String(36), nullable=True),
        sa.Column("structured_json", sa.JSON, nullable=True),
        sa.Column("summary_json", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_fit_reports_workspace_job", "fit_reports", ["workspace_id", "job_id"])
    op.create_index("ix_fit_reports_job_report_id", "fit_reports", ["job_report_id"])
    op.create_index("ix_fit_reports_status", "fit_reports", ["status"])


def downgrade() -> None:
    op.drop_table("fit_reports")
    op.drop_table("job_reports")
    op.execute("DROP TYPE IF EXISTS fit_report_status")
    op.execute("DROP TYPE IF EXISTS job_report_status")

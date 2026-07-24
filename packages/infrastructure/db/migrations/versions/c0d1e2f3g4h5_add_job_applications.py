"""add job_applications, application_events, application_actions tables

Adds the workspace-private application tracker: one row per submitted (or
planned) application, an append-only event timeline, and a to-do/action table
that drives the planner's "Today" view. Also adds workspaces.planner_settings_json
to hold the per-workspace planner configuration (weekly targets, follow-up/ghost
thresholds, etc.) as a single JSON blob.

Revision ID: c0d1e2f3g4h5
Revises: b9c0d1e2f3g4
Create Date: 2026-07-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c0d1e2f3g4h5"
down_revision = "b9c0d1e2f3g4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_applications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id"), nullable=False),
        # NOT NULL: every application references a job row — either URL-imported
        # or created from a pasted JD (synthetic manual:// canonical_url), both
        # via the shared manual_import ingest pipeline. No bare/off-platform rows.
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column(
            "profile_id", sa.String(36), sa.ForeignKey("candidate_profiles.id"), nullable=True
        ),
        # planned | applied | in_review | interviewing | offer | rejected | withdrawn | ghosted
        # Plain string (not Enum) — see Job.status comment for why enums are avoided here.
        sa.Column("status", sa.String(50), nullable=False, server_default="planned"),
        sa.Column("lane", sa.String(8), nullable=True),  # a | b | c (effort tier)
        sa.Column("excitement", sa.Integer(), nullable=True),  # 1-3 gut-feel rating
        sa.Column("channel", sa.String(32), nullable=True),  # cold_apply|referral|recruiter|linkedin
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resume_run_id", sa.String(36), nullable=True),  # -> resume_tailor run (no FK)
        sa.Column("contact_name", sa.String(255), nullable=True),
        sa.Column("contact_note", sa.Text, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("closed_reason", sa.Text, nullable=True),
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
        # One application per (workspace, job). job_id is NOT NULL, so this is a
        # plain uniqueness guarantee — re-importing the same job resolves to the
        # existing application row rather than creating a duplicate.
        sa.UniqueConstraint("workspace_id", "job_id", name="uq_job_applications_workspace_job"),
    )
    op.create_index("ix_job_applications_workspace_id", "job_applications", ["workspace_id"])
    op.create_index("ix_job_applications_job_id", "job_applications", ["job_id"])
    op.create_index("ix_job_applications_profile_id", "job_applications", ["profile_id"])
    op.create_index("ix_job_applications_status", "job_applications", ["status"])

    op.create_table(
        "application_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "application_id",
            sa.String(36),
            sa.ForeignKey("job_applications.id"),
            nullable=False,
        ),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("message", sa.Text, nullable=True),
        sa.Column("payload_json", sa.JSON, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_application_events_application_id", "application_events", ["application_id"]
    )
    op.create_index("ix_application_events_workspace_id", "application_events", ["workspace_id"])
    op.create_index("ix_application_events_created_at", "application_events", ["created_at"])

    op.create_table(
        "application_actions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        # Nullable: a global action (e.g. "run a discovery to refill the queue")
        # is not tied to any single application.
        sa.Column(
            "application_id",
            sa.String(36),
            sa.ForeignKey("job_applications.id"),
            nullable=True,
        ),
        sa.Column("type", sa.String(32), nullable=False),  # apply|follow_up|networking|prep|thank_you|custom|global
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),  # pending|done|snoozed|dismissed
        sa.Column("auto_generated", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("payload_json", sa.JSON, nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
    op.create_index("ix_application_actions_workspace_id", "application_actions", ["workspace_id"])
    op.create_index(
        "ix_application_actions_application_id", "application_actions", ["application_id"]
    )
    op.create_index("ix_application_actions_status", "application_actions", ["status"])

    op.add_column(
        "workspaces",
        sa.Column("planner_settings_json", sa.JSON, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workspaces", "planner_settings_json")

    op.drop_index("ix_application_actions_status", table_name="application_actions")
    op.drop_index("ix_application_actions_application_id", table_name="application_actions")
    op.drop_index("ix_application_actions_workspace_id", table_name="application_actions")
    op.drop_table("application_actions")

    op.drop_index("ix_application_events_created_at", table_name="application_events")
    op.drop_index("ix_application_events_workspace_id", table_name="application_events")
    op.drop_index("ix_application_events_application_id", table_name="application_events")
    op.drop_table("application_events")

    op.drop_index("ix_job_applications_status", table_name="job_applications")
    op.drop_index("ix_job_applications_profile_id", table_name="job_applications")
    op.drop_index("ix_job_applications_job_id", table_name="job_applications")
    op.drop_index("ix_job_applications_workspace_id", table_name="job_applications")
    op.drop_table("job_applications")

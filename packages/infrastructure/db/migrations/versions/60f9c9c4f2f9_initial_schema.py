"""initial schema

Revision ID: 60f9c9c4f2f9
Revises:
Create Date: 2026-06-19

Creates all tables:
  Core:   workspaces, runs, tasks, task_events, artifacts
  Agent:  agent_invocations, agent_tool_events, agent_validation_results
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "60f9c9c4f2f9"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # workspaces
    # ------------------------------------------------------------------
    op.create_table(
        "workspaces",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    # ------------------------------------------------------------------
    # runs
    # ------------------------------------------------------------------
    op.create_table(
        "runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id"),
            nullable=False,
        ),
        sa.Column("run_type", sa.String(100), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="queued"),
        sa.Column("input_snapshot_json", sa.JSON, nullable=True),
        sa.Column("result_summary_json", sa.JSON, nullable=True),
        sa.Column("correlation_id", sa.String(36), nullable=True),
        sa.Column("schema_version", sa.String(20), nullable=False, server_default="v1"),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_runs_workspace_id", "runs", ["workspace_id"])
    op.create_index("ix_runs_status", "runs", ["status"])
    op.create_index("ix_runs_correlation_id", "runs", ["correlation_id"])

    # ------------------------------------------------------------------
    # tasks
    # ------------------------------------------------------------------
    op.create_table(
        "tasks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "run_id", sa.String(36), sa.ForeignKey("runs.id"), nullable=False
        ),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("task_type", sa.String(100), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="queued"),
        sa.Column("attempt_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer, nullable=False, server_default="3"),
        sa.Column("idempotency_key", sa.String(255), nullable=True, unique=True),
        sa.Column("schema_version", sa.String(20), nullable=False, server_default="v1"),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_tasks_run_id", "tasks", ["run_id"])
    op.create_index("ix_tasks_workspace_id", "tasks", ["workspace_id"])
    op.create_index("ix_tasks_status", "tasks", ["status"])

    # ------------------------------------------------------------------
    # task_events
    # ------------------------------------------------------------------
    op.create_table(
        "task_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "task_id", sa.String(36), sa.ForeignKey("tasks.id"), nullable=False
        ),
        sa.Column(
            "run_id", sa.String(36), sa.ForeignKey("runs.id"), nullable=False
        ),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("message", sa.Text, nullable=True),
        sa.Column("payload_json", sa.JSON, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_task_events_task_id", "task_events", ["task_id"])
    op.create_index("ix_task_events_run_id", "task_events", ["run_id"])
    op.create_index("ix_task_events_created_at", "task_events", ["created_at"])

    # ------------------------------------------------------------------
    # artifacts
    # ------------------------------------------------------------------
    op.create_table(
        "artifacts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "run_id", sa.String(36), sa.ForeignKey("runs.id"), nullable=False
        ),
        sa.Column(
            "task_id", sa.String(36), sa.ForeignKey("tasks.id"), nullable=True
        ),
        sa.Column("artifact_type", sa.String(100), nullable=False),
        sa.Column("storage_uri", sa.Text, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("metadata_json", sa.JSON, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_artifacts_run_id", "artifacts", ["run_id"])
    op.create_index("ix_artifacts_task_id", "artifacts", ["task_id"])

    # ------------------------------------------------------------------
    # agent_invocations
    # ------------------------------------------------------------------
    op.create_table(
        "agent_invocations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "run_id", sa.String(36), sa.ForeignKey("runs.id"), nullable=False
        ),
        sa.Column(
            "task_id", sa.String(36), sa.ForeignKey("tasks.id"), nullable=False
        ),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("agent_id", sa.String(100), nullable=False),
        sa.Column("session_key", sa.String(512), nullable=False, unique=True),
        sa.Column("skill_contract_version", sa.String(100), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("input_spec_uri", sa.Text, nullable=True),
        sa.Column("output_manifest_uri", sa.Text, nullable=True),
        sa.Column("stdout_uri", sa.Text, nullable=True),
        sa.Column("stderr_uri", sa.Text, nullable=True),
        sa.Column("exit_code", sa.Integer, nullable=True),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_agent_invocations_run_id", "agent_invocations", ["run_id"])
    op.create_index("ix_agent_invocations_task_id", "agent_invocations", ["task_id"])
    op.create_index("ix_agent_invocations_status", "agent_invocations", ["status"])

    # ------------------------------------------------------------------
    # agent_tool_events
    # ------------------------------------------------------------------
    op.create_table(
        "agent_tool_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "invocation_id",
            sa.String(36),
            sa.ForeignKey("agent_invocations.id"),
            nullable=False,
        ),
        sa.Column("tool_name", sa.String(100), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=True),
        sa.Column("output_hash", sa.String(64), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="ok"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_agent_tool_events_invocation_id", "agent_tool_events", ["invocation_id"]
    )
    op.create_index(
        "ix_agent_tool_events_created_at", "agent_tool_events", ["created_at"]
    )

    # ------------------------------------------------------------------
    # agent_validation_results
    # ------------------------------------------------------------------
    op.create_table(
        "agent_validation_results",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "invocation_id",
            sa.String(36),
            sa.ForeignKey("agent_invocations.id"),
            nullable=False,
        ),
        sa.Column("validator_name", sa.String(100), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("errors_json", sa.JSON, nullable=True),
        sa.Column("warnings_json", sa.JSON, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_agent_validation_results_invocation_id",
        "agent_validation_results",
        ["invocation_id"],
    )


def downgrade() -> None:
    op.drop_table("agent_validation_results")
    op.drop_table("agent_tool_events")
    op.drop_table("agent_invocations")
    op.drop_table("artifacts")
    op.drop_table("task_events")
    op.drop_table("tasks")
    op.drop_table("runs")
    op.drop_table("workspaces")

"""add partial unique index enforcing one active agent run per workspace+type

Revision ID: x5y6z7a8b9c0
Revises: w4x5y6z7a8b9
Create Date: 2026-07-10
"""

from __future__ import annotations

from alembic import op

revision = "x5y6z7a8b9c0"
down_revision = "w4x5y6z7a8b9"
branch_labels = None
depends_on = None

# Scoped to the OpenClaw agent-driven run types only. job_report/fit_report
# intentionally allow multiple concurrent runs per workspace (batch analyze).
_AGENT_RUN_TYPES = ("job_discovery", "job_research", "run_reflection", "candidate_story_build")

_INDEX_NAME = "uq_active_agent_run_per_workspace_type"


def upgrade() -> None:
    run_types = ", ".join(f"'{rt}'" for rt in _AGENT_RUN_TYPES)

    # Real environments can already have orphaned queued/running runs (worker
    # crashed, task lost, etc.) that would violate this constraint the moment
    # it's created. Auto-close all but the most recent per (workspace_id,
    # run_type) rather than assuming the table is clean. This is a one-time
    # data fixup, not reversible in downgrade() — we don't try to guess which
    # rows to reopen.
    op.execute(
        f"""
        WITH ranked AS (
            SELECT id, ROW_NUMBER() OVER (
                PARTITION BY workspace_id, run_type
                ORDER BY created_at DESC
            ) AS rn
            FROM runs
            WHERE status IN ('queued', 'running')
              AND run_type IN ({run_types})
        )
        UPDATE runs
        SET status = 'failed',
            error_code = 'STALE_DUPLICATE_AUTO_CLOSED',
            error_message = 'Auto-closed by migration {revision}: superseded by a more recent run of the same type in this workspace, blocking uq_active_agent_run_per_workspace_type.'
        WHERE id IN (SELECT id FROM ranked WHERE rn > 1)
        """
    )

    op.execute(
        f"""
        CREATE UNIQUE INDEX {_INDEX_NAME}
        ON runs (workspace_id, run_type)
        WHERE status IN ('queued', 'running')
          AND run_type IN ({run_types})
        """
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {_INDEX_NAME}")

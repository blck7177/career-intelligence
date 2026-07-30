"""drop candidate_story_bank

The story-bank feature's code was removed from the production tree, but the
migration that created its table was not — so the database has carried a table
with no model behind it ever since. That orphan is 3 of the last drift items
between models.py and the migration chain, and the only ones that cannot be
settled by adding a declaration: re-declaring a model for a deleted feature to
keep a comparison quiet would be the wrong fix.

The two rows in the dev database were prototype output written on 2026-07-02
into the `dev-test` workspace, not user data. They were dumped to
dev_note/career/candidate_story_bank_rows_0730.json before this ran; the
downgrade below restores the table's structure but, as with any drop, not its
contents.

Revision ID: i6j7k8l9m0n1
Revises: h5i6j7k8l9m0
Create Date: 2026-07-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "i6j7k8l9m0n1"
down_revision = "h5i6j7k8l9m0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("candidate_story_bank")


def downgrade() -> None:
    # Mirrors w4x5y6z7a8b9's upgrade() exactly, so a downgrade lands on the same
    # structure the chain has always produced at that point.
    op.create_table(
        "candidate_story_bank",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("candidate_profiles.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("workspace_id", sa.String(36), nullable=False, index=True),
        sa.Column("run_id", sa.String(36), nullable=True),
        sa.Column("experience_ref", sa.String(50), nullable=False),
        sa.Column("story_id", sa.String(100), nullable=False),
        sa.Column("workstream_title", sa.String(500), nullable=False),
        sa.Column("bullets_covered", sa.JSON, nullable=True),
        sa.Column("narrative", sa.Text, nullable=True),
        sa.Column("workflow", sa.JSON, nullable=True),
        sa.Column("evidence_items", sa.JSON, nullable=True),
        sa.Column("candidate_questions", sa.JSON, nullable=True),
        sa.Column("do_not_claim", sa.JSON, nullable=True),
        sa.Column("research_basis", sa.JSON, nullable=True),
        sa.Column("user_edited_at", sa.DateTime(timezone=True), nullable=True),
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

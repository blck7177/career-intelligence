"""add_user_identities

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-06-22

Introduce user_identities table to decouple the local User from any
specific auth provider.

Migration plan (upgrade):
  1. Create user_identities table.
  2. Data migration: copy clerk_user_id from users → user_identities
     (provider='clerk').
  3. Drop ix_users_clerk_user_id index.
  4. Drop clerk_user_id column from users.

Migration plan (downgrade — fully reversible):
  1. Add clerk_user_id column back to users (nullable first).
  2. Data migration: populate clerk_user_id from user_identities
     WHERE provider='clerk'.
  3. Make clerk_user_id NOT NULL + recreate unique index.
  4. Drop user_identities table.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.sql import column, table

revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Create user_identities table
    # ------------------------------------------------------------------
    op.create_table(
        "user_identities",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("provider_user_id", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_user_identities_user_id", "user_identities", ["user_id"])
    op.create_index(
        "ix_user_identities_provider",
        "user_identities",
        ["provider", "provider_user_id"],
        unique=True,
    )

    # ------------------------------------------------------------------
    # 2. Data migration: copy existing clerk_user_id → user_identities
    # ------------------------------------------------------------------
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            INSERT INTO user_identities (id, user_id, provider, provider_user_id, email, created_at)
            SELECT
                gen_random_uuid()::text,
                id,
                'clerk',
                clerk_user_id,
                email,
                created_at
            FROM users
            WHERE clerk_user_id IS NOT NULL
            """
        )
    )

    # ------------------------------------------------------------------
    # 3. Drop old index + column
    # ------------------------------------------------------------------
    op.drop_index("ix_users_clerk_user_id", table_name="users")
    op.drop_column("users", "clerk_user_id")


def downgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Add clerk_user_id back (nullable to allow backfill first)
    # ------------------------------------------------------------------
    op.add_column(
        "users",
        sa.Column("clerk_user_id", sa.String(128), nullable=True),
    )

    # ------------------------------------------------------------------
    # 2. Data migration: repopulate from user_identities
    # ------------------------------------------------------------------
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            UPDATE users u
            SET clerk_user_id = ui.provider_user_id
            FROM user_identities ui
            WHERE ui.user_id = u.id
              AND ui.provider = 'clerk'
            """
        )
    )

    # ------------------------------------------------------------------
    # 3. Make NOT NULL + unique index
    # ------------------------------------------------------------------
    op.alter_column("users", "clerk_user_id", nullable=False)
    op.create_index("ix_users_clerk_user_id", "users", ["clerk_user_id"], unique=True)

    # ------------------------------------------------------------------
    # 4. Drop user_identities
    # ------------------------------------------------------------------
    op.drop_index("ix_user_identities_provider", table_name="user_identities")
    op.drop_index("ix_user_identities_user_id", table_name="user_identities")
    op.drop_table("user_identities")

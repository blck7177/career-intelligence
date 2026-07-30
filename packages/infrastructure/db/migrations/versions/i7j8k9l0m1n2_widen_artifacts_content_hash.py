"""widen artifacts.content_hash to 128

The initial schema declared VARCHAR(64), presumably for a bare sha256 hex
digest. What the code actually writes is `sha256:<64 hex>` — 71 characters
(packages/infrastructure/services/job_report_service.py::_compute_file_sha256).
Nothing ever widened the column.

So any database built from this migration chain rejects every content_hash the
report services produce. It has never been hit because the running database was
created by `Base.metadata.create_all()` from the model's String(128) and stamped
afterwards — it has been 128 all along, while the chain said 64. The two only
diverged in the dark, and only surfaced when `alembic check` was pointed at both.

287 rows of 71-char hashes exist in the dev database, none longer, so 128 keeps
the original headroom rather than trimming to a number that happens to fit today.

No-op where the column is already 128; a real widening on any database that was
in fact built from the chain. Widening never truncates, so no data check is
needed on the way up. The downgrade narrows back and WILL fail if 65+ char
values are present — correct: refusing beats silently truncating a digest.

Revision ID: i7j8k9l0m1n2
Revises: i6j7k8l9m0n1
Create Date: 2026-07-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "i7j8k9l0m1n2"
down_revision = "i6j7k8l9m0n1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "artifacts",
        "content_hash",
        existing_type=sa.String(64),
        type_=sa.String(128),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "artifacts",
        "content_hash",
        existing_type=sa.String(128),
        type_=sa.String(64),
        existing_nullable=True,
    )

"""rename role category keys to role_category in job_reports JSON columns

Revision ID: m4n5o6p7q8r9
Revises: l2m3n4o5p6q7
Create Date: 2026-06-25

Backfill structured_json and summary_json:
  primary_workstream      -> primary_role_category
  secondary_workstreams   -> secondary_role_categories
  workstream_evidence     -> role_category_evidence
  workstream_confidence   -> role_category_confidence
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "m4n5o6p7q8r9"
down_revision = "l2m3n4o5p6q7"
branch_labels = None
depends_on = None

_KEY_MAP = {
    "primary_workstream": "primary_role_category",
    "secondary_workstreams": "secondary_role_categories",
    "workstream_evidence": "role_category_evidence",
    "workstream_confidence": "role_category_confidence",
}


def _remap_keys(obj: dict | None) -> dict | None:
    if not isinstance(obj, dict):
        return obj
    out: dict = {}
    for key, value in obj.items():
        new_key = _KEY_MAP.get(key, key)
        out[new_key] = value
    return out


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, structured_json, summary_json FROM job_reports")
    ).fetchall()
    for row in rows:
        structured = _remap_keys(row.structured_json)
        summary = _remap_keys(row.summary_json)
        if structured != row.structured_json or summary != row.summary_json:
            conn.execute(
                sa.text(
                    "UPDATE job_reports "
                    "SET structured_json = CAST(:structured AS JSON), "
                    "summary_json = CAST(:summary AS JSON) "
                    "WHERE id = :id"
                ),
                {
                    "id": row.id,
                    "structured": json.dumps(structured) if structured is not None else None,
                    "summary": json.dumps(summary) if summary is not None else None,
                },
            )


def downgrade() -> None:
    reverse = {v: k for k, v in _KEY_MAP.items()}
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, structured_json, summary_json FROM job_reports")
    ).fetchall()

    def _remap_back(obj: dict | None) -> dict | None:
        if not isinstance(obj, dict):
            return obj
        return {reverse.get(key, key): value for key, value in obj.items()}

    for row in rows:
        structured = _remap_back(row.structured_json)
        summary = _remap_back(row.summary_json)
        if structured != row.structured_json or summary != row.summary_json:
            conn.execute(
                sa.text(
                    "UPDATE job_reports "
                    "SET structured_json = CAST(:structured AS JSON), "
                    "summary_json = CAST(:summary AS JSON) "
                    "WHERE id = :id"
                ),
                {
                    "id": row.id,
                    "structured": json.dumps(structured) if structured is not None else None,
                    "summary": json.dumps(summary) if summary is not None else None,
                },
            )

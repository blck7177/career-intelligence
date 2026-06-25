"""
API DTOs for discovered jobs.

Jobs are written to the database only after Validator Gate passes.
These DTOs reflect the actual Job ORM model fields.
Internal fields (jd_text, jd_hash, raw_payload_json) are not exposed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class JobRead(BaseModel):
    """A canonical job record returned by the API."""

    id: str
    canonical_url: str
    source_url: str
    source_type: str
    title: str
    company: str
    location: Optional[str] = None
    status: str  # "discovered" | "reportable" | "invalid" | "stale"
    discovered_run_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    last_seen_at: Optional[datetime] = None
    # Populated when include_report_summary=true (from latest active job report)
    primary_workstream: Optional[str] = None
    seniority_inferred: Optional[str] = None
    workstream_confidence: Optional[str] = None  # high | medium | low

    model_config = {"from_attributes": True}


class JobList(BaseModel):
    items: list[JobRead]
    total: int

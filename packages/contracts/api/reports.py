"""
API DTOs for job intelligence and candidate fit reports.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ReportRead(BaseModel):
    """A generated report (job intelligence or candidate fit)."""

    id: str
    job_id: str
    report_type: str  # "job_intelligence" | "candidate_fit"
    status: str       # "pending" | "ready" | "failed"
    content_uri: Optional[str] = None
    summary: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ReportList(BaseModel):
    items: list[ReportRead]
    total: int

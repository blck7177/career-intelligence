"""
API DTOs for fit report list/summary endpoints.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class FitReportSummary(BaseModel):
    id: str
    job_id: str
    candidate_profile_id: Optional[str] = None
    overall_match_score: int
    recommended_next_action: Optional[str] = None
    status: str
    updated_at: datetime

    model_config = {"from_attributes": True}


class FitReportSummaryList(BaseModel):
    items: list[FitReportSummary]
    total: int

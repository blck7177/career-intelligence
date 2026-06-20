"""
API DTOs for discovered jobs.

Jobs are written to the database only after Validator Gate passes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class JobRead(BaseModel):
    """A normalized job record returned by the API."""

    id: str
    workspace_id: str
    run_id: Optional[str] = None
    source: str
    title: Optional[str] = None
    company: Optional[str] = None
    location: Optional[str] = None
    url: Optional[str] = None
    normalized: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class JobList(BaseModel):
    items: list[JobRead]
    total: int

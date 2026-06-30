"""
API DTOs for discovered jobs.

Jobs are written to the database only after Validator Gate passes.
These DTOs reflect the actual Job ORM model fields.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class JDStructured(BaseModel):
    """Structured fields extracted from JD text during discovery."""

    responsibilities: list[str] = []
    required_skills: list[str] = []
    preferred_skills: list[str] = []
    tools_mentioned: list[str] = []
    seniority_inferred: str = "unknown"
    likely_tasks: list[str] = []
    likely_stakeholders: list[str] = []
    inferred_team_context: str = ""
    role_category: Optional[str] = None


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
    latest_job_report_id: Optional[str] = None
    primary_role_category: Optional[str] = None
    seniority_inferred: Optional[str] = None
    role_category_confidence: Optional[str] = None  # high | medium | low
    # Structured JD extraction (from discovery-time LLM call)
    jd_structured: Optional[JDStructured] = None
    # Whether the current workspace has bookmarked this job
    is_favorited: bool = False

    model_config = {"from_attributes": True}


class JobList(BaseModel):
    items: list[JobRead]
    total: int


class FavoriteResponse(BaseModel):
    favorited: bool


class JobImportRequest(BaseModel):
    """Import a single job by URL."""

    url: str

    model_config = {"json_schema_extra": {"examples": [{"url": "https://boards.greenhouse.io/acme/jobs/123"}]}}


class JobImportResponse(BaseModel):
    """Result of a job import."""

    job: JobRead
    created: bool
    jd_fetched: bool


class BatchArchiveRequest(BaseModel):
    job_ids: list[str]


class BatchArchiveResponse(BaseModel):
    archived_count: int


class BatchAnalyzeRequest(BaseModel):
    job_ids: list[str]
    profile_id: Optional[str] = None


class BatchAnalyzeResponse(BaseModel):
    run_ids: list[str]
    skipped: list[str]
    report_first: list[str] = []

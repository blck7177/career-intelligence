"""
Admin Cost API — LLM usage and cost visibility.

Contract:
  GET /api/admin/cost/by-run-type            → list[CostByRunType]
  GET /api/admin/cost/runs/{run_id}          → list[LLMUsageEventRead]

Auth: require_admin — 403 for non-admin users.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from apps.api.dependencies.auth import require_admin
from apps.api.dependencies.db import get_db
from packages.infrastructure.db.models import User
from packages.infrastructure.db.repositories import (
    LLMUsageEventRepository,
    RunRepository,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/cost", tags=["admin-cost"])


class LLMUsageEventRead(BaseModel):
    id: str
    run_id: Optional[str] = None
    task_id: Optional[str] = None
    workspace_id: Optional[str] = None
    call_site: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: Optional[float] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class CostByRunType(BaseModel):
    run_type: str
    llm_calls: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: float


@router.get("/by-run-type", response_model=list[CostByRunType])
def admin_cost_by_run_type(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> list[CostByRunType]:
    """Aggregate LLM cost grouped by run_type (admin only)."""
    repo = LLMUsageEventRepository(db)
    rows = repo.summary_by_run_type()
    return [CostByRunType(**r) for r in rows]


@router.get("/runs/{run_id}", response_model=list[LLMUsageEventRead])
def admin_cost_for_run(
    run_id: str,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> list[LLMUsageEventRead]:
    """List LLM usage events for a specific run (admin only)."""
    run = RunRepository(db).get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    repo = LLMUsageEventRepository(db)
    events = repo.list_for_run(run_id)
    return [LLMUsageEventRead.model_validate(e) for e in events]

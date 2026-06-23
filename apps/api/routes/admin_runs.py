"""
Admin Runs API — debug/ops view of runs, tasks, events, agent invocations.

Contract:
  GET /api/admin/runs                              → RunList  (cross-workspace)
  GET /api/admin/runs/{run_id}/tasks              → list[TaskRead]
  GET /api/admin/runs/{run_id}/events             → list[TaskEventRead]
  GET /api/admin/runs/{run_id}/agent-invocations  → list[AgentInvocationRead]
  POST /api/admin/runs/{run_id}/cancel            → RunRead

Auth: require_admin — 403 for non-admin users.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from apps.api.dependencies.auth import require_admin
from apps.api.dependencies.db import get_db
from packages.contracts.api.runs import (
    AgentInvocationRead,
    RunList,
    RunRead,
    TaskEventRead,
    TaskRead,
)
from packages.infrastructure.db.models import User
from packages.infrastructure.db.repositories import (
    AgentInvocationRepository,
    RunRepository,
    TaskEventRepository,
    TaskRepository,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/runs", tags=["admin-runs"])


@router.get("", response_model=RunList)
def admin_list_runs(
    workspace_id: Optional[str] = Query(None, description="Filter by workspace_id"),
    status: Optional[str] = Query(None, description="Filter by run status"),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> RunList:
    """List runs across all workspaces (admin only)."""
    run_repo = RunRepository(db)
    if workspace_id:
        runs = run_repo.list_for_workspace(workspace_id, limit=limit)
    else:
        runs = run_repo.list_all(limit=limit, status=status)
    return RunList(items=[RunRead.model_validate(r) for r in runs], total=len(runs))


@router.get("/{run_id}/tasks", response_model=list[TaskRead])
def admin_list_tasks(
    run_id: str,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> list[TaskRead]:
    """List tasks for any run (admin only)."""
    run = RunRepository(db).get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    tasks = TaskRepository(db).list_for_run(run_id)
    return [TaskRead.model_validate(t) for t in tasks]


@router.get("/{run_id}/events", response_model=list[TaskEventRead])
def admin_list_events(
    run_id: str,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> list[TaskEventRead]:
    """List task events for any run (admin only)."""
    run = RunRepository(db).get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    events = TaskEventRepository(db).list_for_run(run_id)
    return [TaskEventRead.model_validate(e) for e in events]


@router.get("/{run_id}/agent-invocations", response_model=list[AgentInvocationRead])
def admin_list_agent_invocations(
    run_id: str,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> list[AgentInvocationRead]:
    """List agent invocations for any run (admin only)."""
    run = RunRepository(db).get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    invocations = AgentInvocationRepository(db).list_for_run(run_id)
    return [AgentInvocationRead.model_validate(inv) for inv in invocations]


@router.post("/{run_id}/cancel", response_model=RunRead)
def admin_cancel_run(
    run_id: str,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> RunRead:
    """Cancel any run regardless of workspace (admin only)."""
    run_repo = RunRepository(db)
    run = run_repo.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status in ("succeeded", "failed", "cancelled"):
        raise HTTPException(
            status_code=409, detail=f"Run already in terminal state: {run.status}"
        )
    run = run_repo.set_status(run_id, "cancelled")
    db.commit()
    return RunRead.model_validate(run)

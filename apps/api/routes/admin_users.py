"""
Admin Users API — user and workspace management for ops/developer console.

Contract:
  GET /api/admin/users                    → list of UserRead
  GET /api/admin/workspaces               → list of WorkspaceRead

Auth: require_admin — 403 for non-admin users.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from apps.api.dependencies.auth import require_admin
from apps.api.dependencies.db import get_db
from packages.infrastructure.db.models import User, Workspace
from packages.infrastructure.db.repositories import UserRepository, WorkspaceRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin-users"])


# ---------------------------------------------------------------------------
# Response DTOs
# ---------------------------------------------------------------------------


class UserRead(BaseModel):
    id: str
    email: str
    is_admin: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class WorkspaceRead(BaseModel):
    id: str
    name: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/users", response_model=list[UserRead])
def admin_list_users(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> list[UserRead]:
    """List all users (admin only)."""
    users = db.query(User).order_by(User.created_at.desc()).all()
    return [UserRead.model_validate(u) for u in users]


@router.get("/workspaces", response_model=list[WorkspaceRead])
def admin_list_workspaces(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> list[WorkspaceRead]:
    """List all workspaces (admin only)."""
    workspaces = db.query(Workspace).order_by(Workspace.created_at.desc()).all()
    return [WorkspaceRead.model_validate(w) for w in workspaces]

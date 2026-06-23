"""
Profile API — GET and PUT the candidate profile for the current workspace.

Contract:
  GET /api/app/profile   → ProfileRead  (404 if not yet created)
  PUT /api/app/profile   → ProfileRead  (upserts, recalculates profile_hash)

Auth: get_current_workspace — every authenticated user has one profile per workspace.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from apps.api.dependencies.auth import get_current_workspace
from apps.api.dependencies.db import get_db
from packages.infrastructure.db.models import Workspace
from packages.infrastructure.db.repositories import ProfileRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/app/profile", tags=["profile"])


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class ProfileRead(BaseModel):
    id: str
    workspace_id: str
    summary: Optional[str] = None
    experience_summary: Optional[str] = None
    education_summary: Optional[str] = None
    technical_skills: Optional[list] = None
    domain_areas: Optional[list] = None
    preferences_json: Optional[dict] = None
    years_of_experience: Optional[int] = None
    profile_hash: str

    model_config = {"from_attributes": True}


class ProfileUpdate(BaseModel):
    summary: Optional[str] = None
    experience_summary: Optional[str] = None
    education_summary: Optional[str] = None
    technical_skills: Optional[list] = None
    domain_areas: Optional[list] = None
    preferences_json: Optional[dict] = None
    years_of_experience: Optional[int] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compute_hash(data: ProfileUpdate) -> str:
    """Stable md5 of the profile content for FitReport cache invalidation."""
    payload = json.dumps(data.model_dump(), sort_keys=True, default=str)
    return hashlib.md5(payload.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=ProfileRead)
def get_profile(
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
):
    """Return the candidate profile for the current workspace. 404 if not yet created."""
    profile = ProfileRepository(db).get_for_workspace(workspace.id)
    if profile is None:
        raise HTTPException(status_code=404, detail="No profile found. Use PUT to create one.")
    return ProfileRead.model_validate(profile)


@router.put("", response_model=ProfileRead)
def upsert_profile(
    body: ProfileUpdate,
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
):
    """Create or update the candidate profile for the current workspace."""
    profile_hash = _compute_hash(body)
    profile = ProfileRepository(db).upsert(
        workspace.id,
        summary=body.summary,
        experience_summary=body.experience_summary,
        education_summary=body.education_summary,
        technical_skills=body.technical_skills,
        domain_areas=body.domain_areas,
        preferences_json=body.preferences_json,
        years_of_experience=body.years_of_experience,
        profile_hash=profile_hash,
    )
    db.commit()
    logger.info("profile: upserted for workspace %s (hash=%s)", workspace.id, profile_hash)
    return ProfileRead.model_validate(profile)

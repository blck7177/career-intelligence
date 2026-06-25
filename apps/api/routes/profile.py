"""
Profile API — GET and PUT the candidate profile for the current workspace.

Contract:
  GET /api/app/profile   → ProfileRead  (auto-creates default if not yet created)
  PUT /api/app/profile   → ProfileRead  (upserts, recalculates profile_hash)

Auth: get_current_workspace — every authenticated user has one profile per workspace.

Default profile: GET auto-creates a hardcoded default profile so FitReport worker
never fails on "no profile found". User can then edit and save via PUT.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends
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
    years_experience: Optional[int] = None
    technical_skills: Optional[list] = None
    domain_experience: Optional[list] = None
    finance_domains: Optional[list] = None
    tools: Optional[list] = None
    representative_projects: Optional[list] = None
    profile_hash: str

    model_config = {"from_attributes": True}


class ProfileUpdate(BaseModel):
    summary: Optional[str] = None
    experience_summary: Optional[str] = None
    education_summary: Optional[str] = None
    years_experience: Optional[int] = None
    technical_skills: Optional[list] = None
    domain_experience: Optional[list] = None
    finance_domains: Optional[list] = None
    tools: Optional[list] = None
    representative_projects: Optional[list] = None


# ---------------------------------------------------------------------------
# Default profile content
# ---------------------------------------------------------------------------

_DEFAULT_PROFILE = ProfileUpdate(
    summary=(
        "Risk analytics professional with experience in quantitative finance. "
        "Edit this profile to personalize your job discovery and fit analysis."
    ),
    experience_summary="",
    education_summary="",
    years_experience=None,
    technical_skills=["Python", "SQL"],
    domain_experience=["market risk"],
    finance_domains=[],
    tools=[],
    representative_projects=[],
)


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
    """Return the candidate profile for the current workspace.
    Auto-creates a default profile if none exists yet.
    """
    profile = ProfileRepository(db).get_for_workspace(workspace.id)
    if profile is None:
        logger.info("profile: no profile for workspace %s — creating default", workspace.id)
        default_hash = _compute_hash(_DEFAULT_PROFILE)
        profile = ProfileRepository(db).upsert(
            workspace.id,
            summary=_DEFAULT_PROFILE.summary,
            experience_summary=_DEFAULT_PROFILE.experience_summary,
            education_summary=_DEFAULT_PROFILE.education_summary,
            years_experience=_DEFAULT_PROFILE.years_experience,
            technical_skills=_DEFAULT_PROFILE.technical_skills,
            domain_experience=_DEFAULT_PROFILE.domain_experience,
            finance_domains=_DEFAULT_PROFILE.finance_domains,
            tools=_DEFAULT_PROFILE.tools,
            representative_projects=_DEFAULT_PROFILE.representative_projects,
            profile_hash=default_hash,
        )
        db.commit()
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
        years_experience=body.years_experience,
        technical_skills=body.technical_skills,
        domain_experience=body.domain_experience,
        finance_domains=body.finance_domains,
        tools=body.tools,
        representative_projects=body.representative_projects,
        profile_hash=profile_hash,
    )
    db.commit()
    logger.info("profile: upserted for workspace %s (hash=%s)", workspace.id, profile_hash)
    return ProfileRead.model_validate(profile)

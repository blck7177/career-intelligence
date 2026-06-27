"""
Profile API — single-profile (default) and multi-profile endpoints.

Single-profile (backward-compatible):
  GET  /api/app/profile                → ProfileRead  (most recently updated profile)
  PUT  /api/app/profile                → ProfileRead  (upserts default profile)
  POST /api/app/profile/upload-resume  → { resume_text, char_count, source_filename }

Multi-profile:
  GET    /api/app/profiles              → list[ProfileRead]
  POST   /api/app/profiles              → ProfileRead  (create new profile)
  PUT    /api/app/profiles/{profile_id} → ProfileRead  (update specific profile)
  DELETE /api/app/profiles/{profile_id} → 204
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from apps.api.dependencies.auth import get_current_workspace
from apps.api.dependencies.db import get_db
from packages.infrastructure.db.models import Workspace
from packages.infrastructure.db.repositories import ProfileRepository
from packages.infrastructure.resume_parser import (
    ALLOWED_EXTENSIONS,
    MAX_FILE_BYTES,
    ResumeParseError,
    parse_resume,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/app", tags=["profile"])


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class ProfileRead(BaseModel):
    id: str
    workspace_id: str
    label: str = ""
    summary: Optional[str] = None
    experience_summary: Optional[str] = None
    education_summary: Optional[str] = None
    years_experience: Optional[int] = None
    technical_skills: Optional[list] = None
    subject_areas: Optional[list] = None
    tools: Optional[list] = None
    representative_projects: Optional[list] = None
    profile_hash: str
    search_defaults: Optional[dict] = None

    model_config = {"from_attributes": True}


class ProfileUpdate(BaseModel):
    label: Optional[str] = None
    summary: Optional[str] = None
    experience_summary: Optional[str] = None
    education_summary: Optional[str] = None
    years_experience: Optional[int] = None
    technical_skills: Optional[list] = None
    subject_areas: Optional[list] = None
    tools: Optional[list] = None
    representative_projects: Optional[list] = None


# ---------------------------------------------------------------------------
# Default profile content
# ---------------------------------------------------------------------------

_DEFAULT_PROFILE = ProfileUpdate(
    summary=(
        "Professional with relevant experience in your field. "
        "Edit this profile to personalize your job discovery and fit analysis."
    ),
    experience_summary="",
    education_summary="",
    years_experience=None,
    technical_skills=["Python", "SQL"],
    subject_areas=[],
    tools=[],
    representative_projects=[],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compute_hash(data: ProfileUpdate) -> str:
    """Stable md5 of the profile content for FitReport cache invalidation."""
    payload = json.dumps(data.model_dump(exclude={"label", "search_defaults"}), sort_keys=True, default=str)
    return hashlib.md5(payload.encode()).hexdigest()


def _assert_profile_owned(profile, workspace: Workspace) -> None:
    if profile is None or profile.workspace_id != workspace.id:
        raise HTTPException(status_code=404, detail="Profile not found.")


# ---------------------------------------------------------------------------
# Single-profile endpoints (backward-compatible)
# ---------------------------------------------------------------------------


@router.get("/profile", response_model=ProfileRead)
def get_profile(
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
):
    """Return the default (most recently updated) profile. Auto-creates if none exists."""
    repo = ProfileRepository(db)
    profile = repo.get_for_workspace(workspace.id)
    if profile is None:
        logger.info("profile: no profile for workspace %s — creating default", workspace.id)
        default_hash = _compute_hash(_DEFAULT_PROFILE)
        profile = repo.create(
            workspace.id,
            summary=_DEFAULT_PROFILE.summary,
            experience_summary=_DEFAULT_PROFILE.experience_summary,
            education_summary=_DEFAULT_PROFILE.education_summary,
            years_experience=_DEFAULT_PROFILE.years_experience,
            technical_skills=_DEFAULT_PROFILE.technical_skills,
            subject_areas=_DEFAULT_PROFILE.subject_areas,
            tools=_DEFAULT_PROFILE.tools,
            representative_projects=_DEFAULT_PROFILE.representative_projects,
            profile_hash=default_hash,
        )
        db.commit()
    return ProfileRead.model_validate(profile)


@router.put("/profile", response_model=ProfileRead)
def upsert_profile(
    body: ProfileUpdate,
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
):
    """Create or update the default profile for the current workspace."""
    profile_hash = _compute_hash(body)
    profile = ProfileRepository(db).upsert(
        workspace.id,
        summary=body.summary,
        experience_summary=body.experience_summary,
        education_summary=body.education_summary,
        years_experience=body.years_experience,
        technical_skills=body.technical_skills,
        subject_areas=body.subject_areas,
        tools=body.tools,
        representative_projects=body.representative_projects,
        profile_hash=profile_hash,
    )
    db.commit()
    logger.info("profile: upserted for workspace %s (hash=%s)", workspace.id, profile_hash)
    return ProfileRead.model_validate(profile)


@router.post("/profile/upload-resume")
async def upload_resume(
    file: UploadFile = File(...),
    workspace: Workspace = Depends(get_current_workspace),
):
    """Parse an uploaded PDF or DOCX resume into plain text."""
    filename = file.filename or "unknown"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if f".{ext}" not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '.{ext}'. Accepted: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    file_bytes = await file.read()

    if len(file_bytes) > MAX_FILE_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"File too large ({len(file_bytes) / 1024 / 1024:.1f} MB). Maximum is 10 MB.",
        )

    try:
        resume_text = parse_resume(file_bytes, filename)
    except ResumeParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    logger.info("profile: parsed resume '%s' for workspace %s (%d chars)", filename, workspace.id, len(resume_text))
    return {
        "resume_text": resume_text,
        "char_count": len(resume_text),
        "source_filename": filename,
    }


# ---------------------------------------------------------------------------
# Multi-profile endpoints
# ---------------------------------------------------------------------------


@router.get("/profiles", response_model=list[ProfileRead])
def list_profiles(
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
):
    """List all profiles for the current workspace."""
    profiles = ProfileRepository(db).list_for_workspace(workspace.id)
    return [ProfileRead.model_validate(p) for p in profiles]


@router.post("/profiles", response_model=ProfileRead, status_code=201)
def create_profile(
    body: ProfileUpdate,
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
):
    """Create a new profile."""
    profile_hash = _compute_hash(body)
    profile = ProfileRepository(db).create(
        workspace.id,
        label=body.label or "",
        summary=body.summary,
        experience_summary=body.experience_summary,
        education_summary=body.education_summary,
        years_experience=body.years_experience,
        technical_skills=body.technical_skills,
        subject_areas=body.subject_areas,
        tools=body.tools,
        representative_projects=body.representative_projects,
        profile_hash=profile_hash,
    )
    db.commit()
    logger.info("profile: created %s for workspace %s (label=%r)", profile.id, workspace.id, body.label)
    return ProfileRead.model_validate(profile)


@router.put("/profiles/{profile_id}", response_model=ProfileRead)
def update_profile(
    profile_id: str,
    body: ProfileUpdate,
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
):
    """Update a specific profile."""
    repo = ProfileRepository(db)
    profile = repo.get_by_id(profile_id)
    _assert_profile_owned(profile, workspace)

    profile_hash = _compute_hash(body)
    profile = repo.update(
        profile_id,
        label=body.label,
        summary=body.summary,
        experience_summary=body.experience_summary,
        education_summary=body.education_summary,
        years_experience=body.years_experience,
        technical_skills=body.technical_skills,
        subject_areas=body.subject_areas,
        tools=body.tools,
        representative_projects=body.representative_projects,
        profile_hash=profile_hash,
    )
    db.commit()
    logger.info("profile: updated %s (hash=%s)", profile_id, profile_hash)
    return ProfileRead.model_validate(profile)


@router.delete("/profiles/{profile_id}", status_code=204)
def delete_profile(
    profile_id: str,
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
):
    """Delete a profile. Cannot delete the last one."""
    repo = ProfileRepository(db)
    profile = repo.get_by_id(profile_id)
    _assert_profile_owned(profile, workspace)

    if repo.count_for_workspace(workspace.id) <= 1:
        raise HTTPException(status_code=400, detail="Cannot delete the only profile.")

    repo.delete(profile_id)
    db.commit()
    logger.info("profile: deleted %s", profile_id)


@router.put("/profiles/{profile_id}/search-defaults", status_code=204)
def update_search_defaults(
    profile_id: str,
    body: dict,
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
):
    """Save search preferences for a profile. Does not affect profile_hash."""
    repo = ProfileRepository(db)
    profile = repo.get_by_id(profile_id)
    _assert_profile_owned(profile, workspace)

    repo.update_search_defaults(profile_id, body)
    db.commit()

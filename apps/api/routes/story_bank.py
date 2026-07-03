"""
Story Bank API — read and update candidate story bank entries.

Contract:
  GET   /api/app/profiles/{profile_id}/story-bank         → list[StoryBankEntryRead]
  PATCH /api/app/profiles/{profile_id}/story-bank/{id}    → StoryBankEntryRead

Triggering a new story bank build goes through the standard runs API:
  POST /api/app/runs  { run_type: "candidate_story_build", input_snapshot: { profile_id } }

Auth:
  All endpoints require a valid workspace JWT.
  profile_id is validated to belong to the current workspace.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from apps.api.dependencies.auth import get_current_workspace
from apps.api.dependencies.db import get_db
from packages.infrastructure.db.models import Workspace
from packages.infrastructure.db.repositories import ProfileRepository, StoryBankRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/app/profiles", tags=["story-bank"])


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class StoryBankEntryRead(BaseModel):
    id: str
    profile_id: str
    experience_ref: str
    story_id: str
    workstream_title: str
    bullets_covered: Optional[list] = None
    narrative: Optional[str] = None
    workflow: Optional[dict] = None
    evidence_items: Optional[list] = None
    candidate_questions: Optional[list] = None
    do_not_claim: Optional[list] = None
    research_basis: Optional[list] = None
    user_edited_at: Optional[str] = None  # ISO8601 or null
    created_at: str
    updated_at: str


class StoryBankEntryUpdate(BaseModel):
    workstream_title: Optional[str] = None
    narrative: Optional[str] = None
    workflow: Optional[dict] = None
    evidence_items: Optional[list] = None
    candidate_questions: Optional[list] = None
    do_not_claim: Optional[list] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _assert_profile_owned(profile_id: str, workspace: Workspace, db: Session) -> None:
    profile = ProfileRepository(db).get_by_id(profile_id)
    if not profile or profile.workspace_id != workspace.id:
        raise HTTPException(status_code=404, detail="Profile not found.")


def _entry_to_read(row) -> StoryBankEntryRead:
    return StoryBankEntryRead(
        id=row.id,
        profile_id=row.profile_id,
        experience_ref=row.experience_ref,
        story_id=row.story_id,
        workstream_title=row.workstream_title,
        bullets_covered=row.bullets_covered,
        narrative=row.narrative,
        workflow=row.workflow,
        evidence_items=row.evidence_items,
        candidate_questions=row.candidate_questions,
        do_not_claim=row.do_not_claim,
        research_basis=row.research_basis,
        user_edited_at=row.user_edited_at.isoformat() if row.user_edited_at else None,
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/{profile_id}/story-bank", response_model=list[StoryBankEntryRead])
def list_story_bank(
    profile_id: str,
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
) -> list[StoryBankEntryRead]:
    """Return all story bank entries for a profile, ordered by experience_ref."""
    _assert_profile_owned(profile_id, workspace, db)
    rows = StoryBankRepository(db).list_for_profile(profile_id)
    return [_entry_to_read(r) for r in rows]


@router.patch("/{profile_id}/story-bank/{entry_id}", response_model=StoryBankEntryRead)
def update_story_bank_entry(
    profile_id: str,
    entry_id: str,
    body: StoryBankEntryUpdate,
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
) -> StoryBankEntryRead:
    """Update a story bank entry. Sets user_edited_at to mark it as user-reviewed."""
    _assert_profile_owned(profile_id, workspace, db)

    repo = StoryBankRepository(db)
    entry = repo.get(entry_id)
    if not entry or entry.profile_id != profile_id:
        raise HTTPException(status_code=404, detail="Story bank entry not found.")

    updated = repo.update_story(
        entry_id,
        narrative=body.narrative,
        workflow=body.workflow,
        evidence_items=body.evidence_items,
        candidate_questions=body.candidate_questions,
        do_not_claim=body.do_not_claim,
        workstream_title=body.workstream_title,
    )
    db.commit()
    return _entry_to_read(updated)

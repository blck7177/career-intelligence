"""Health check endpoint — required by Docker Compose healthcheck."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from apps.api.dependencies.db import get_db

router = APIRouter(tags=["health"])


@router.get("/healthz")
def health(db: Session = Depends(get_db)) -> dict:
    """Returns 200 if API and DB are reachable."""
    db.execute(text("SELECT 1"))
    return {"status": "ok"}

"""
FastAPI auth dependencies — Clerk JWT verification + user/workspace resolution.

Flow per request:
  1. Frontend attaches Clerk JWT as  Authorization: Bearer <token>
  2. get_current_user() validates the JWT against Clerk's JWKS endpoint
  3. On first login the User row is auto-provisioned (and a Workspace)
  4. get_current_workspace() resolves the user's workspace

Environment variables required:
  CLERK_JWKS_URL   — e.g. https://<your-clerk-domain>/.well-known/jwks.json
                     Defaults to https://api.clerk.com/v1/jwks if unset.
  CLERK_AUDIENCE   — optional expected audience claim (leave unset to skip check)
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from apps.api.dependencies.db import get_db
from packages.infrastructure.db.models import User, Workspace
from packages.infrastructure.db.repositories import (
    UserIdentityRepository,
    UserRepository,
    WorkspaceRepository,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# JWKS client — module-level singleton; PyJWKClient handles caching internally
# (cache_jwk_set=True, lifespan=300s by default).  Signing keys are also
# cached with cache_keys=True so the JWKS endpoint is not hit on every request.
# ---------------------------------------------------------------------------

_CLERK_JWKS_URL = os.environ.get("CLERK_JWKS_URL", "https://api.clerk.com/v1/jwks")
_CLERK_AUDIENCE = os.environ.get("CLERK_AUDIENCE")

_jwks_client = jwt.PyJWKClient(_CLERK_JWKS_URL, cache_keys=True, lifespan=300)


def _verify_clerk_jwt(token: str) -> dict:
    """Validate a Clerk JWT and return the decoded payload."""
    try:
        signing_key = _jwks_client.get_signing_key_from_jwt(token)
    except (jwt.exceptions.PyJWKClientError, jwt.exceptions.DecodeError) as exc:
        # DecodeError covers malformed JWTs (not enough segments, bad base64, etc.)
        # PyJWKClientError covers JWKS fetch failures and unknown key IDs.
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")

    decode_kwargs: dict = {
        "algorithms": ["RS256"],
        "options": {"verify_exp": True},
    }
    if _CLERK_AUDIENCE:
        decode_kwargs["audience"] = _CLERK_AUDIENCE

    try:
        payload = jwt.decode(token, signing_key.key, **decode_kwargs)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired.")
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")

    return payload


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------


def get_current_user(
    authorization: Optional[str] = Header(None, alias="Authorization"),
    db: Session = Depends(get_db),
) -> User:
    """
    Validate the Clerk Bearer JWT and return the local User record.
    Auto-provisions the User (and a Workspace) on first login.
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required.")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization header must be 'Bearer <token>'.")
    token = authorization.removeprefix("Bearer ").strip()

    payload = _verify_clerk_jwt(token)
    clerk_user_id: Optional[str] = payload.get("sub")
    if not clerk_user_id:
        raise HTTPException(status_code=401, detail="Token missing 'sub' claim.")

    user_repo = UserRepository(db)
    user = user_repo.get_by_provider("clerk", clerk_user_id)

    if user is None:
        # Auto-provision user + workspace on first login.
        email: str = (
            payload.get("email")
            or payload.get("email_address")
            or f"{clerk_user_id}@unknown"
        )
        user = _provision_user(db, clerk_user_id=clerk_user_id, email=email)
        logger.info("auth: provisioned new user %s (%s)", user.id, email)

    return user


def get_current_workspace(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Workspace:
    """
    Resolve the workspace for the authenticated user.
    Every user has exactly one workspace at beta; raises 403 if none found.
    """
    ws_repo = WorkspaceRepository(db)
    workspace = ws_repo.get_for_user(user.id)
    if workspace is None:
        raise HTTPException(
            status_code=403,
            detail="No workspace found for this user. Contact support.",
        )
    return workspace


def require_admin(user: User = Depends(get_current_user)) -> User:
    """
    Dependency for admin-only endpoints.
    Raises 403 unless the resolved user has is_admin=True.
    Set is_admin=true in Postgres for developer/ops accounts:
      UPDATE users SET is_admin=true WHERE email='admin@example.com';
    """
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required.")
    return user


# ---------------------------------------------------------------------------
# Provisioning helper (called by get_current_user on first login)
# ---------------------------------------------------------------------------


def _provision_user(db: Session, *, clerk_user_id: str, email: str) -> User:
    """
    Create User + UserIdentity + Workspace + WorkspaceMember in a single flush.
    Called inside the existing db session from get_current_user.
    """
    user_repo = UserRepository(db)
    identity_repo = UserIdentityRepository(db)
    ws_repo = WorkspaceRepository(db)

    user = user_repo.create(email=email)
    identity_repo.create(
        user_id=user.id,
        provider="clerk",
        provider_user_id=clerk_user_id,
        email=email,
    )

    workspace_name = email.split("@")[0] if "@" in email else clerk_user_id
    workspace = ws_repo.create(name=workspace_name)
    ws_repo.add_member(workspace_id=workspace.id, user_id=user.id, role="owner")

    logger.info(
        "auth: provisioned workspace %s for user %s", workspace.id, user.id
    )
    return user

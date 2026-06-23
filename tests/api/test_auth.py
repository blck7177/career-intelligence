"""
Auth boundary regression tests.

Verifies that every product and admin endpoint rejects unauthenticated requests,
and that malformed Bearer tokens return 401 rather than 500.

The DB dependency is overridden with a MagicMock so these tests require no
running database.  No real Clerk JWKS network calls are made:
  - Missing Authorization header → 422 (FastAPI required-parameter validation)
  - Malformed JWT (bad base64 / wrong segment count) → 401 (DecodeError caught)
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Shared fixture: TestClient with DB mocked out
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client() -> TestClient:  # type: ignore[misc]
    from apps.api.dependencies.db import get_db
    from apps.api.main import app

    def _mock_db():
        yield MagicMock()

    app.dependency_overrides[get_db] = _mock_db
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# No Authorization header → 422 (FastAPI rejects before reaching auth logic)
# ---------------------------------------------------------------------------

PRODUCT_ROUTES = [
    ("GET", "/api/app/jobs"),
    ("GET", "/api/app/runs"),
    ("GET", "/api/app/profile"),
]

ADMIN_ROUTES = [
    ("GET", "/api/admin/runs"),
    ("GET", "/api/admin/users"),
]


@pytest.mark.parametrize("method,path", PRODUCT_ROUTES)
def test_product_routes_reject_missing_auth(client: TestClient, method: str, path: str):
    """Product routes must not be publicly accessible."""
    response = getattr(client, method.lower())(path)
    assert response.status_code in (401, 422), (
        f"{method} {path} returned {response.status_code}; "
        "expected 401 or 422 (unauthenticated)"
    )


@pytest.mark.parametrize("method,path", ADMIN_ROUTES)
def test_admin_routes_reject_missing_auth(client: TestClient, method: str, path: str):
    """Admin routes must not be publicly accessible."""
    response = getattr(client, method.lower())(path)
    assert response.status_code in (401, 422), (
        f"{method} {path} returned {response.status_code}; "
        "expected 401 or 422 (unauthenticated)"
    )


# ---------------------------------------------------------------------------
# Malformed Bearer token → 401 (not 500)
# ---------------------------------------------------------------------------

MALFORMED_TOKENS = [
    "not-a-jwt",          # no segments at all
    "x.y.z",              # 3 segments but not valid base64
    "Bearer",             # keyword only, no token
    "",                   # empty string after Bearer prefix
]


@pytest.mark.parametrize("raw_token", MALFORMED_TOKENS)
def test_malformed_token_returns_401(client: TestClient, raw_token: str):
    """A malformed Bearer token must return 401, never 500."""
    response = client.get(
        "/api/app/jobs",
        headers={"Authorization": f"Bearer {raw_token}"},
    )
    assert response.status_code == 401, (
        f"Bearer '{raw_token}' returned {response.status_code}; expected 401"
    )


# ---------------------------------------------------------------------------
# Health endpoint is publicly accessible (no auth required)
# ---------------------------------------------------------------------------


def test_healthz_is_public(client: TestClient):
    """/healthz must return 200 without any auth header."""
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json().get("status") == "ok"

"""
Startup and route-registration smoke tests.

These tests import the FastAPI app and inspect its route table — no HTTP calls,
no DB, no network.  They act as a fast gate that catches the class of bug where
a module referenced in main.py does not actually exist (ModuleNotFoundError),
or a router was accidentally dropped from include_router().
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Import smoke
# ---------------------------------------------------------------------------


def test_app_imports_cleanly():
    """from apps.api.main import app must not raise ModuleNotFoundError."""
    from apps.api.main import app  # noqa: F401 — import is the assertion

    assert app is not None


def test_app_title():
    from apps.api.main import app

    assert app.title == "Career OpenClaw API"


# ---------------------------------------------------------------------------
# Route-registration checks
# ---------------------------------------------------------------------------


def _registered_paths() -> set[str]:
    """
    Return the set of all route paths registered on the app.

    FastAPI wraps included routers as _IncludedRouter objects whose actual
    routes live on `.original_router.routes`.  Walk both levels to collect
    every registered path.
    """
    from apps.api.main import app

    paths: set[str] = set()
    for entry in app.routes:
        # Top-level route (e.g. the root redirect)
        if hasattr(entry, "path"):
            paths.add(entry.path)
        # Included router — FastAPI wraps it in _IncludedRouter
        orig = getattr(entry, "original_router", None)
        if orig is not None:
            for route in getattr(orig, "routes", []):
                if hasattr(route, "path"):
                    paths.add(route.path)
    return paths


EXPECTED_PREFIXES = [
    # product routes
    "/api/app/jobs",
    "/api/app/runs",
    "/api/app/fit-reports",
    "/api/app/job-reports",
    "/api/app/profile",
    # admin routes
    "/api/admin/runs",
    "/api/admin/users",
    # infra
    "/healthz",
]


@pytest.mark.parametrize("prefix", EXPECTED_PREFIXES)
def test_route_prefix_registered(prefix: str):
    """Every expected route prefix must appear in the app's route table."""
    paths = _registered_paths()
    assert any(p.startswith(prefix) for p in paths), (
        f"Route prefix {prefix!r} not found. Registered paths: {sorted(paths)}"
    )

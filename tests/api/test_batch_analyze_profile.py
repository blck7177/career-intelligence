"""
batch_analyze — client-supplied profile_id must belong to the calling workspace.

batch_analyze threads body.profile_id into the fit_report run (directly) and the
job_report run (as auto_fit_profile_id, which the job_report auto-chain forwards
to the chained fit_report). Now that fit_report actually resolves that profile to
score against, a foreign profile_id must be rejected at the entry point — mirrors
the job_discovery/run_reflection cross-workspace checks in create_run.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

WS_ID = "ws-batch-test"
OTHER_WS_ID = "ws-other-tenant"


def _ws() -> SimpleNamespace:
    return SimpleNamespace(id=WS_ID, name="test", tier="beta")


def _profile(profile_id: str, workspace_id: str) -> SimpleNamespace:
    return SimpleNamespace(id=profile_id, workspace_id=workspace_id)


@pytest.fixture()
def make_client():
    from apps.api.dependencies.auth import get_current_workspace
    from apps.api.dependencies.db import get_db
    from apps.api.main import app

    def _factory():
        def _mock_db():
            yield MagicMock()

        app.dependency_overrides[get_db] = _mock_db
        app.dependency_overrides[get_current_workspace] = _ws
        return TestClient(app, raise_server_exceptions=False)

    yield _factory
    app.dependency_overrides.clear()


_BODY = {"job_ids": ["job-1"], "profile_id": "profile-target"}


def test_batch_analyze_foreign_profile_returns_403(make_client):
    client = make_client()
    other_profile = _profile("profile-target", workspace_id=OTHER_WS_ID)

    with (
        patch("apps.api.routes.jobs.RunRepository") as MockRunRepo,
        patch("apps.api.routes.jobs.ProfileRepository") as MockProfileRepo,
    ):
        MockRunRepo.return_value.list_for_workspace.return_value = []
        MockProfileRepo.return_value.get_by_id.return_value = other_profile
        resp = client.post("/api/app/jobs/batch-analyze", json=_BODY)

    assert resp.status_code == 403, resp.text
    assert "profile_id" in resp.json()["detail"]


def test_batch_analyze_nonexistent_profile_returns_403(make_client):
    client = make_client()

    with (
        patch("apps.api.routes.jobs.RunRepository") as MockRunRepo,
        patch("apps.api.routes.jobs.ProfileRepository") as MockProfileRepo,
    ):
        MockRunRepo.return_value.list_for_workspace.return_value = []
        MockProfileRepo.return_value.get_by_id.return_value = None
        resp = client.post("/api/app/jobs/batch-analyze", json=_BODY)

    assert resp.status_code == 403, resp.text


def test_batch_analyze_without_profile_id_skips_check(make_client):
    """No profile_id → no ownership lookup (job loop just skips all unknown jobs)."""
    client = make_client()

    with (
        patch("apps.api.routes.jobs.RunRepository") as MockRunRepo,
        patch("apps.api.routes.jobs.ProfileRepository") as MockProfileRepo,
        patch("apps.api.routes.jobs.JobRepository") as MockJobRepo,
    ):
        MockRunRepo.return_value.list_for_workspace.return_value = []
        MockJobRepo.return_value.get.return_value = None  # job not in workspace → skipped
        resp = client.post("/api/app/jobs/batch-analyze", json={"job_ids": ["job-1"]})

    assert resp.status_code == 200, resp.text
    MockProfileRepo.return_value.get_by_id.assert_not_called()

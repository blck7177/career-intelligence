"""
create_run — cross-workspace reference rejection for run_reflection.run_id and
job_discovery.profile_id.

Found via real-data incident analysis (not hypothetical): reflect_run.py's
_build_reflection_payload() and search_run.py's _load_profile() fetch these
client-supplied ids by id alone, with no check that they belong to the
calling workspace — see
dev_note/career/phase20-launch-hardening/openclaw_http_migration_0712/README.md.
Unlike job_id (jobs/job_reports are intentionally global/shared, not
per-workspace), a prior run and a candidate profile are workspace-private, so
these must be verified before the worker ever touches them.

Not-found and found-but-other-workspace both return the same 403 (not 404 vs
403) — distinguishing them would let a workspace enumerate valid run_id/
profile_id values belonging to other workspaces.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

WS_ID = "ws-cross-test"
OTHER_WS_ID = "ws-other-tenant"
_NOW = datetime.now(timezone.utc)


def _ws(tier: str = "beta") -> SimpleNamespace:
    return SimpleNamespace(id=WS_ID, name="test", tier=tier, created_at=_NOW, updated_at=_NOW)


def _run(run_id: str, workspace_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=run_id, workspace_id=workspace_id, run_type="job_discovery", status="succeeded",
        correlation_id=None, schema_version="v1", error_code=None, error_message=None,
        result_summary_json=None, created_at=_NOW, updated_at=_NOW,
    )


def _profile(profile_id: str, workspace_id: str) -> SimpleNamespace:
    return SimpleNamespace(id=profile_id, workspace_id=workspace_id)


_REFLECTION_BODY = {
    "run_type": "run_reflection",
    "input_snapshot": {"run_id": "run-target"},
}

_DISCOVERY_BODY_WITH_PROFILE = {
    "run_type": "job_discovery",
    "input_snapshot": {
        "raw_user_request": "market risk analyst roles in NYC",
        "search_mode": "profile_guided",
        "profile_id": "profile-target",
    },
}

_DISCOVERY_BODY_NO_PROFILE = {
    "run_type": "job_discovery",
    "input_snapshot": {
        "raw_user_request": "market risk analyst roles in NYC",
        "search_mode": "direct",
    },
}

_FIT_BODY_WITH_PROFILE = {
    "run_type": "fit_report",
    "input_snapshot": {"job_id": "job-1", "profile_id": "profile-target"},
}

_FIT_BODY_NO_PROFILE = {
    "run_type": "fit_report",
    "input_snapshot": {"job_id": "job-1"},
}


@pytest.fixture()
def make_client():
    from apps.api.dependencies.auth import get_current_workspace
    from apps.api.dependencies.db import get_db
    from apps.api.main import app

    def _factory():
        def _mock_db():
            yield MagicMock()

        def _mock_ws():
            return _ws()

        app.dependency_overrides[get_db] = _mock_db
        app.dependency_overrides[get_current_workspace] = _mock_ws
        return TestClient(app, raise_server_exceptions=False)

    yield _factory
    app.dependency_overrides.clear()


def _created_run(run_type: str) -> SimpleNamespace:
    return SimpleNamespace(
        id="run-new", workspace_id=WS_ID, run_type=run_type, status="queued",
        correlation_id="c1", schema_version="v1", error_code=None, error_message=None,
        result_summary_json=None, created_at=_NOW, updated_at=_NOW,
    )


class TestRunReflectionCrossWorkspace:
    def test_reflecting_another_workspaces_run_returns_403(self, make_client):
        client = make_client()
        other_run = _run("run-target", workspace_id=OTHER_WS_ID)

        with patch("apps.api.routes.runs.RunRepository") as MockRunRepo:
            MockRunRepo.return_value.get.return_value = other_run
            resp = client.post("/api/app/runs", json=_REFLECTION_BODY)

        assert resp.status_code == 403, resp.text
        assert "run_id" in resp.json()["detail"]

    def test_reflecting_nonexistent_run_returns_403_not_404(self, make_client):
        """Same 403 as cross-workspace — must not reveal whether the id exists at all."""
        client = make_client()

        with patch("apps.api.routes.runs.RunRepository") as MockRunRepo:
            MockRunRepo.return_value.get.return_value = None
            resp = client.post("/api/app/runs", json=_REFLECTION_BODY)

        assert resp.status_code == 403, resp.text

    def test_reflecting_own_run_proceeds(self, make_client):
        client = make_client()
        own_run = _run("run-target", workspace_id=WS_ID)

        with (
            patch("apps.api.routes.runs.RunRepository") as MockRunRepo,
            patch("apps.api.routes.runs.TaskRepository") as MockTaskRepo,
            patch("apps.api.routes.runs.get_quota_rule") as mock_rule,
            patch("apps.api.routes.runs._get_celery"),
        ):
            mock_rule.return_value = None
            MockRunRepo.return_value.get.return_value = own_run
            MockRunRepo.return_value.create.return_value = _created_run("run_reflection")
            MockTaskRepo.return_value.create.return_value = SimpleNamespace(id="task-new")

            resp = client.post("/api/app/runs", json=_REFLECTION_BODY)

        assert resp.status_code == 201, resp.text


class TestJobDiscoveryProfileCrossWorkspace:
    def test_discovery_with_another_workspaces_profile_returns_403(self, make_client):
        client = make_client()
        other_profile = _profile("profile-target", workspace_id=OTHER_WS_ID)

        with patch("apps.api.routes.runs.ProfileRepository") as MockProfileRepo:
            MockProfileRepo.return_value.get_by_id.return_value = other_profile
            resp = client.post("/api/app/runs", json=_DISCOVERY_BODY_WITH_PROFILE)

        assert resp.status_code == 403, resp.text
        assert "profile_id" in resp.json()["detail"]

    def test_discovery_with_nonexistent_profile_returns_403_not_404(self, make_client):
        client = make_client()

        with patch("apps.api.routes.runs.ProfileRepository") as MockProfileRepo:
            MockProfileRepo.return_value.get_by_id.return_value = None
            resp = client.post("/api/app/runs", json=_DISCOVERY_BODY_WITH_PROFILE)

        assert resp.status_code == 403, resp.text

    def test_discovery_with_own_profile_proceeds(self, make_client):
        client = make_client()
        own_profile = _profile("profile-target", workspace_id=WS_ID)

        with (
            patch("apps.api.routes.runs.ProfileRepository") as MockProfileRepo,
            patch("apps.api.routes.runs.RunRepository") as MockRunRepo,
            patch("apps.api.routes.runs.TaskRepository") as MockTaskRepo,
            patch("apps.api.routes.runs.get_quota_rule") as mock_rule,
            patch("apps.api.routes.runs._get_celery"),
        ):
            mock_rule.return_value = None
            MockProfileRepo.return_value.get_by_id.return_value = own_profile
            MockRunRepo.return_value.create.return_value = _created_run("job_discovery")
            MockTaskRepo.return_value.create.return_value = SimpleNamespace(id="task-new")

            resp = client.post("/api/app/runs", json=_DISCOVERY_BODY_WITH_PROFILE)

        assert resp.status_code == 201, resp.text

    def test_discovery_without_profile_id_skips_check(self, make_client):
        """profile_id omitted entirely (direct/exploratory search_mode) — no lookup at all."""
        client = make_client()

        with (
            patch("apps.api.routes.runs.ProfileRepository") as MockProfileRepo,
            patch("apps.api.routes.runs.RunRepository") as MockRunRepo,
            patch("apps.api.routes.runs.TaskRepository") as MockTaskRepo,
            patch("apps.api.routes.runs.get_quota_rule") as mock_rule,
            patch("apps.api.routes.runs._get_celery"),
        ):
            mock_rule.return_value = None
            MockRunRepo.return_value.create.return_value = _created_run("job_discovery")
            MockTaskRepo.return_value.create.return_value = SimpleNamespace(id="task-new")

            resp = client.post("/api/app/runs", json=_DISCOVERY_BODY_NO_PROFILE)

        assert resp.status_code == 201, resp.text
        MockProfileRepo.return_value.get_by_id.assert_not_called()


class TestFitReportProfileCrossWorkspace:
    """fit_report.profile_id is now honored by the worker (selects which profile
    to score against), so create_run must verify workspace ownership up front —
    same treatment as job_discovery.profile_id."""

    def test_fit_report_with_another_workspaces_profile_returns_403(self, make_client):
        client = make_client()
        other_profile = _profile("profile-target", workspace_id=OTHER_WS_ID)

        with patch("apps.api.routes.runs.ProfileRepository") as MockProfileRepo:
            MockProfileRepo.return_value.get_by_id.return_value = other_profile
            resp = client.post("/api/app/runs", json=_FIT_BODY_WITH_PROFILE)

        assert resp.status_code == 403, resp.text
        assert "profile_id" in resp.json()["detail"]

    def test_fit_report_with_nonexistent_profile_returns_403_not_404(self, make_client):
        client = make_client()

        with patch("apps.api.routes.runs.ProfileRepository") as MockProfileRepo:
            MockProfileRepo.return_value.get_by_id.return_value = None
            resp = client.post("/api/app/runs", json=_FIT_BODY_WITH_PROFILE)

        assert resp.status_code == 403, resp.text

    def test_fit_report_with_own_profile_proceeds(self, make_client):
        client = make_client()
        own_profile = _profile("profile-target", workspace_id=WS_ID)

        with (
            patch("apps.api.routes.runs.ProfileRepository") as MockProfileRepo,
            patch("apps.api.routes.runs.RunRepository") as MockRunRepo,
            patch("apps.api.routes.runs.TaskRepository") as MockTaskRepo,
            patch("apps.api.routes.runs.get_quota_rule") as mock_rule,
            patch("apps.api.routes.runs._get_celery"),
        ):
            mock_rule.return_value = None
            MockProfileRepo.return_value.get_by_id.return_value = own_profile
            MockRunRepo.return_value.create.return_value = _created_run("fit_report")
            MockTaskRepo.return_value.create.return_value = SimpleNamespace(id="task-new")

            resp = client.post("/api/app/runs", json=_FIT_BODY_WITH_PROFILE)

        assert resp.status_code == 201, resp.text

    def test_fit_report_without_profile_id_skips_check(self, make_client):
        """profile_id omitted → default profile path, no ownership lookup."""
        client = make_client()

        with (
            patch("apps.api.routes.runs.ProfileRepository") as MockProfileRepo,
            patch("apps.api.routes.runs.RunRepository") as MockRunRepo,
            patch("apps.api.routes.runs.TaskRepository") as MockTaskRepo,
            patch("apps.api.routes.runs.get_quota_rule") as mock_rule,
            patch("apps.api.routes.runs._get_celery"),
        ):
            mock_rule.return_value = None
            MockRunRepo.return_value.create.return_value = _created_run("fit_report")
            MockTaskRepo.return_value.create.return_value = SimpleNamespace(id="task-new")

            resp = client.post("/api/app/runs", json=_FIT_BODY_NO_PROFILE)

        assert resp.status_code == 201, resp.text
        MockProfileRepo.return_value.get_by_id.assert_not_called()

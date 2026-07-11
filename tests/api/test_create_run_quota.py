"""
create_run — tier quota + allowed search_depth enforcement.

Patches get_quota_rule at the point of use (apps.api.routes.runs) rather than
touching the real configs/quotas.yaml, so these tests don't depend on — or
break when someone tunes — the actual tier numbers.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from packages.domain.quota.tiers import QuotaRule

WS_ID = "ws-quota-test"
_NOW = datetime.now(timezone.utc)


def _ws(tier: str = "new") -> SimpleNamespace:
    return SimpleNamespace(id=WS_ID, name="test", tier=tier, created_at=_NOW, updated_at=_NOW)


_DISCOVERY_BODY_QUICK = {
    "run_type": "job_discovery",
    "input_snapshot": {
        "raw_user_request": "market risk analyst roles in NYC",
        "search_mode": "direct",
        "search_depth": "quick",
    },
}

_DISCOVERY_BODY_STANDARD = {
    "run_type": "job_discovery",
    "input_snapshot": {
        "raw_user_request": "market risk analyst roles in NYC",
        "search_mode": "direct",
        "search_depth": "standard",
    },
}


@pytest.fixture()
def make_client():
    from apps.api.dependencies.auth import get_current_workspace
    from apps.api.dependencies.db import get_db
    from apps.api.main import app

    def _factory(tier: str = "new"):
        def _mock_db():
            yield MagicMock()

        def _mock_ws():
            return _ws(tier)

        app.dependency_overrides[get_db] = _mock_db
        app.dependency_overrides[get_current_workspace] = _mock_ws
        return TestClient(app, raise_server_exceptions=False)

    yield _factory
    app.dependency_overrides.clear()


class TestSearchDepthGating:
    def test_new_tier_rejects_standard_depth(self, make_client):
        client = make_client(tier="new")
        with patch("apps.api.routes.runs.get_quota_rule") as mock_rule:
            mock_rule.return_value = QuotaRule(monthly_limit=10, allowed_search_depth=("quick",))
            resp = client.post("/api/app/runs", json=_DISCOVERY_BODY_STANDARD)

        assert resp.status_code == 403, resp.text
        assert "standard" in resp.json()["detail"]

    def test_new_tier_allows_quick_depth(self, make_client):
        client = make_client(tier="new")
        created_run = SimpleNamespace(
            id="run-new", workspace_id=WS_ID, run_type="job_discovery", status="queued",
            correlation_id="c1", schema_version="v1", error_code=None, error_message=None,
            result_summary_json=None, created_at=_NOW, updated_at=_NOW,
        )
        with (
            patch("apps.api.routes.runs.get_quota_rule") as mock_rule,
            patch("apps.api.routes.runs.RunRepository") as MockRunRepo,
            patch("apps.api.routes.runs.TaskRepository") as MockTaskRepo,
            patch("apps.api.routes.runs._get_celery"),
        ):
            mock_rule.return_value = QuotaRule(monthly_limit=10, allowed_search_depth=("quick",))
            MockRunRepo.return_value.count_this_month_for_workspace.return_value = 0
            MockRunRepo.return_value.create.return_value = created_run
            MockTaskRepo.return_value.create.return_value = SimpleNamespace(id="task-new")

            resp = client.post("/api/app/runs", json=_DISCOVERY_BODY_QUICK)

        assert resp.status_code == 201, resp.text

    def test_max_tier_allows_deep(self, make_client):
        client = make_client(tier="max")
        body = {**_DISCOVERY_BODY_QUICK, "input_snapshot": {**_DISCOVERY_BODY_QUICK["input_snapshot"], "search_depth": "deep"}}
        created_run = SimpleNamespace(
            id="run-deep", workspace_id=WS_ID, run_type="job_discovery", status="queued",
            correlation_id="c1", schema_version="v1", error_code=None, error_message=None,
            result_summary_json=None, created_at=_NOW, updated_at=_NOW,
        )
        with (
            patch("apps.api.routes.runs.get_quota_rule") as mock_rule,
            patch("apps.api.routes.runs.RunRepository") as MockRunRepo,
            patch("apps.api.routes.runs.TaskRepository") as MockTaskRepo,
            patch("apps.api.routes.runs._get_celery"),
        ):
            mock_rule.return_value = QuotaRule(
                monthly_limit=100, allowed_search_depth=("quick", "standard", "deep")
            )
            MockRunRepo.return_value.count_this_month_for_workspace.return_value = 0
            MockRunRepo.return_value.create.return_value = created_run
            MockTaskRepo.return_value.create.return_value = SimpleNamespace(id="task-new")

            resp = client.post("/api/app/runs", json=body)

        assert resp.status_code == 201, resp.text


class TestMonthlyQuota:
    def test_quota_exhausted_returns_429(self, make_client):
        client = make_client(tier="new")
        with (
            patch("apps.api.routes.runs.get_quota_rule") as mock_rule,
            patch("apps.api.routes.runs.RunRepository") as MockRunRepo,
        ):
            mock_rule.return_value = QuotaRule(monthly_limit=10, allowed_search_depth=("quick",))
            MockRunRepo.return_value.count_this_month_for_workspace.return_value = 10

            resp = client.post("/api/app/runs", json=_DISCOVERY_BODY_QUICK)

        assert resp.status_code == 429, resp.text
        assert "10/10" in resp.json()["detail"]

    def test_quota_not_yet_reached_proceeds(self, make_client):
        client = make_client(tier="new")
        created_run = SimpleNamespace(
            id="run-ok", workspace_id=WS_ID, run_type="job_discovery", status="queued",
            correlation_id="c1", schema_version="v1", error_code=None, error_message=None,
            result_summary_json=None, created_at=_NOW, updated_at=_NOW,
        )
        with (
            patch("apps.api.routes.runs.get_quota_rule") as mock_rule,
            patch("apps.api.routes.runs.RunRepository") as MockRunRepo,
            patch("apps.api.routes.runs.TaskRepository") as MockTaskRepo,
            patch("apps.api.routes.runs._get_celery"),
        ):
            mock_rule.return_value = QuotaRule(monthly_limit=10, allowed_search_depth=("quick",))
            MockRunRepo.return_value.count_this_month_for_workspace.return_value = 9
            MockRunRepo.return_value.create.return_value = created_run
            MockTaskRepo.return_value.create.return_value = SimpleNamespace(id="task-new")

            resp = client.post("/api/app/runs", json=_DISCOVERY_BODY_QUICK)

        assert resp.status_code == 201, resp.text

    def test_no_rule_means_unlimited(self, make_client):
        """get_quota_rule returning None (e.g. beta on job_report) skips quota checks entirely."""
        client = make_client(tier="beta")
        created_run = SimpleNamespace(
            id="run-unlimited", workspace_id=WS_ID, run_type="job_discovery", status="queued",
            correlation_id="c1", schema_version="v1", error_code=None, error_message=None,
            result_summary_json=None, created_at=_NOW, updated_at=_NOW,
        )
        with (
            patch("apps.api.routes.runs.get_quota_rule") as mock_rule,
            patch("apps.api.routes.runs.RunRepository") as MockRunRepo,
            patch("apps.api.routes.runs.TaskRepository") as MockTaskRepo,
            patch("apps.api.routes.runs._get_celery"),
        ):
            mock_rule.return_value = None
            MockRunRepo.return_value.create.return_value = created_run
            MockTaskRepo.return_value.create.return_value = SimpleNamespace(id="task-new")

            resp = client.post("/api/app/runs", json=_DISCOVERY_BODY_QUICK)

        assert resp.status_code == 201, resp.text
        MockRunRepo.return_value.count_this_month_for_workspace.assert_not_called()

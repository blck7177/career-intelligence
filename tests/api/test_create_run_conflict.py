"""
create_run — uq_active_agent_run_per_workspace_type conflict handling.

Verifies that a duplicate active run (same workspace + run_type, already
queued/running) surfaces as a 409 with the existing run_id, instead of an
unhandled 500 from the raw IntegrityError.

No real Postgres constraint is exercised here — RunRepository.create is
patched to raise IntegrityError directly, isolating the API-layer handling
from the DB-layer constraint (verified separately against a live Postgres).
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

WS_ID = "ws-conflict-test"
_NOW = datetime.now(timezone.utc)


def _ws() -> SimpleNamespace:
    # tier="max" so the real quotas.yaml search_depth check (standard is the
    # default JobDiscoveryFrontendInput.search_depth) never interferes here —
    # this file is only about the uq_active_agent_run_per_workspace_type path.
    return SimpleNamespace(id=WS_ID, name="test", tier="max", created_at=_NOW, updated_at=_NOW)


def _existing_run(run_id: str = "run-existing") -> SimpleNamespace:
    return SimpleNamespace(
        id=run_id,
        workspace_id=WS_ID,
        run_type="job_discovery",
        status="running",
        correlation_id=None,
        schema_version="v1",
        error_code=None,
        error_message=None,
        result_summary_json=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


_DISCOVERY_BODY = {
    "run_type": "job_discovery",
    "input_snapshot": {
        "raw_user_request": "market risk analyst roles in NYC",
        "search_mode": "direct",
    },
}


@pytest.fixture()
def client() -> TestClient:  # type: ignore[misc]
    from apps.api.dependencies.auth import get_current_workspace
    from apps.api.dependencies.db import get_db
    from apps.api.main import app

    def _mock_db():
        yield MagicMock()

    def _mock_ws():
        return _ws()

    app.dependency_overrides[get_db] = _mock_db
    app.dependency_overrides[get_current_workspace] = _mock_ws
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


class TestCreateRunConflict:
    def test_duplicate_active_run_returns_409_with_existing_run_id(self, client: TestClient):
        with patch("apps.api.routes.runs.RunRepository") as MockRepo:
            MockRepo.return_value.count_this_month_for_workspace.return_value = 0
            MockRepo.return_value.create.side_effect = IntegrityError("", {}, Exception("dup"))
            MockRepo.return_value.get_active_for_workspace.return_value = _existing_run()

            resp = client.post("/api/app/runs", json=_DISCOVERY_BODY)

        assert resp.status_code == 409, f"Expected 409, got {resp.status_code}: {resp.text}"
        detail = resp.json()["detail"]
        assert detail["existing_run_id"] == "run-existing"
        assert "job_discovery" in detail["message"]

    def test_duplicate_conflict_with_no_locatable_existing_run_still_409s(self, client: TestClient):
        """Existing run vanished between the failed insert and the lookup — degrade gracefully."""
        with patch("apps.api.routes.runs.RunRepository") as MockRepo:
            MockRepo.return_value.count_this_month_for_workspace.return_value = 0
            MockRepo.return_value.create.side_effect = IntegrityError("", {}, Exception("dup"))
            MockRepo.return_value.get_active_for_workspace.return_value = None

            resp = client.post("/api/app/runs", json=_DISCOVERY_BODY)

        assert resp.status_code == 409
        assert resp.json()["detail"]["existing_run_id"] is None

    def test_non_conflicting_create_succeeds(self, client: TestClient):
        created_run = SimpleNamespace(
            id="run-new",
            workspace_id=WS_ID,
            run_type="job_discovery",
            status="queued",
            correlation_id="corr-1",
            schema_version="v1",
            error_code=None,
            error_message=None,
            result_summary_json=None,
            created_at=_NOW,
            updated_at=_NOW,
        )
        with (
            patch("apps.api.routes.runs.RunRepository") as MockRunRepo,
            patch("apps.api.routes.runs.TaskRepository") as MockTaskRepo,
            patch("apps.api.routes.runs._get_celery"),
        ):
            MockRunRepo.return_value.count_this_month_for_workspace.return_value = 0
            MockRunRepo.return_value.create.return_value = created_run
            MockTaskRepo.return_value.create.return_value = SimpleNamespace(id="task-new")

            resp = client.post("/api/app/runs", json=_DISCOVERY_BODY)

        assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
        assert resp.json()["id"] == "run-new"

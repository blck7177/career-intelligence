"""
Phase 7D — Cross-workspace access isolation tests.

Verifies that a user from workspace B cannot access resources owned by workspace A,
even with a valid authentication token.

Strategy:
  - Override get_current_workspace to return a SimpleNamespace workspace (workspace B)
  - Patch Repository classes at the route-module import level so the instantiated
    mock returns controlled objects belonging to workspace A
  - Assert all cross-workspace accesses return 403; same-workspace accesses return 200

No real Clerk JWT calls are made; the auth dependency is fully overridden.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

WS_A = "ws-aaaaaa-1111"  # resource owner
WS_B = "ws-bbbbbb-2222"  # requester (different workspace → access denied)

_NOW = datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# SimpleNamespace factory helpers
# These are plain Python objects; Pydantic reads them via from_attributes=True
# ---------------------------------------------------------------------------


def _ws(ws_id: str) -> SimpleNamespace:
    return SimpleNamespace(id=ws_id, name="test", created_at=_NOW, updated_at=_NOW)


def _run(run_id: str, workspace_id: str = WS_A) -> SimpleNamespace:
    return SimpleNamespace(
        id=run_id,
        workspace_id=workspace_id,
        run_type="job_discovery",
        status="succeeded",
        correlation_id=None,
        schema_version="v1",
        error_code=None,
        error_message=None,
        result_summary_json=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _job(job_id: str, discovered_run_id: str | None = "run-aaa") -> SimpleNamespace:
    return SimpleNamespace(
        id=job_id,
        canonical_url="https://example.com/job/1",
        source_url="https://example.com/job/1",
        source_type="ats",
        title="Senior Analyst",
        company="Acme Corp",
        location="New York",
        jd_text=None,
        jd_hash=None,
        raw_payload_json=None,
        status="discovered",
        discovered_run_id=discovered_run_id,
        discovered_task_id=None,
        created_at=_NOW,
        updated_at=_NOW,
        last_seen_at=None,
    )


def _fit_report(report_id: str, workspace_id: str = WS_A) -> SimpleNamespace:
    return SimpleNamespace(
        id=report_id,
        workspace_id=workspace_id,
        job_id="job-001",
        job_report_id="jr-001",
        candidate_profile_id=None,
        profile_hash="abc123",
        prompt_version="v1",
        overall_match_score=72,
        status="active",
        structured_json={},
        summary_json={},
        narrative_artifact_id=None,
        structured_artifact_id=None,
        created_at=_NOW,
        updated_at=_NOW,
        superseded_at=None,
    )


# ---------------------------------------------------------------------------
# Client fixture: workspace B is the authenticated workspace
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client_b() -> TestClient:  # type: ignore[misc]
    from apps.api.dependencies.auth import get_current_workspace
    from apps.api.dependencies.db import get_db
    from apps.api.main import app

    def _mock_db():
        yield MagicMock()

    def _mock_ws_b():
        return _ws(WS_B)

    app.dependency_overrides[get_db] = _mock_db
    app.dependency_overrides[get_current_workspace] = _mock_ws_b
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Phase 7D-1: Run isolation
# ---------------------------------------------------------------------------


class TestRunIsolation:
    def test_cross_workspace_run_returns_403(self, client_b: TestClient):
        """GET /api/app/runs/{run_id} — run belongs to ws_a, requester is ws_b → 403."""
        run_a = _run("run-aaa", workspace_id=WS_A)

        with patch("apps.api.routes.runs.RunRepository") as MockRepo:
            MockRepo.return_value.get.return_value = run_a
            resp = client_b.get("/api/app/runs/run-aaa")

        assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"
        assert "denied" in resp.json().get("detail", "").lower()

    def test_nonexistent_run_returns_404(self, client_b: TestClient):
        """GET /api/app/runs/{run_id} — run does not exist → 404."""
        with patch("apps.api.routes.runs.RunRepository") as MockRepo:
            MockRepo.return_value.get.return_value = None
            resp = client_b.get("/api/app/runs/does-not-exist")

        assert resp.status_code == 404

    def test_same_workspace_run_returns_200(self, client_b: TestClient):
        """GET /api/app/runs/{run_id} — run belongs to ws_b (same workspace) → 200."""
        run_b = _run("run-bbb", workspace_id=WS_B)

        with patch("apps.api.routes.runs.RunRepository") as MockRepo:
            MockRepo.return_value.get.return_value = run_b
            resp = client_b.get("/api/app/runs/run-bbb")

        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        assert resp.json()["id"] == "run-bbb"

    def test_cross_workspace_cancel_returns_403(self, client_b: TestClient):
        """POST /api/app/runs/{run_id}/cancel — cross-workspace cancel → 403."""
        run_a = _run("run-cancel", workspace_id=WS_A)
        run_a.status = "running"

        with patch("apps.api.routes.runs.RunRepository") as MockRepo:
            MockRepo.return_value.get.return_value = run_a
            resp = client_b.post("/api/app/runs/run-cancel/cancel")

        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Phase 7D-2: Job isolation
# ---------------------------------------------------------------------------


class TestJobIsolation:
    def test_cross_workspace_job_returns_403(self, client_b: TestClient):
        """GET /api/app/jobs/{job_id} — job discovered by ws_a run → 403 for ws_b."""
        job = _job("job-aaa", discovered_run_id="run-aaa")
        run_a = _run("run-aaa", workspace_id=WS_A)

        with (
            patch("apps.api.routes.jobs.JobRepository") as MockJobRepo,
            patch("apps.api.routes.jobs.RunRepository") as MockRunRepo,
        ):
            MockJobRepo.return_value.get.return_value = job
            MockRunRepo.return_value.get.return_value = run_a
            resp = client_b.get("/api/app/jobs/job-aaa")

        assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"

    def test_nonexistent_job_returns_404(self, client_b: TestClient):
        """GET /api/app/jobs/{job_id} — job not found → 404."""
        with patch("apps.api.routes.jobs.JobRepository") as MockJobRepo:
            MockJobRepo.return_value.get.return_value = None
            resp = client_b.get("/api/app/jobs/does-not-exist")

        assert resp.status_code == 404

    def test_job_with_missing_run_link_returns_403(self, client_b: TestClient):
        """GET /api/app/jobs/{job_id} — job has no discovered_run_id → 403 (broken ownership chain)."""
        job = _job("job-no-run", discovered_run_id=None)

        with patch("apps.api.routes.jobs.JobRepository") as MockJobRepo:
            MockJobRepo.return_value.get.return_value = job
            resp = client_b.get("/api/app/jobs/job-no-run")

        assert resp.status_code == 403, f"Expected 403 for broken chain, got {resp.status_code}"

    def test_same_workspace_job_returns_200(self, client_b: TestClient):
        """GET /api/app/jobs/{job_id} — job discovered by ws_b run → 200."""
        job = _job("job-bbb", discovered_run_id="run-bbb")
        run_b = _run("run-bbb", workspace_id=WS_B)

        with (
            patch("apps.api.routes.jobs.JobRepository") as MockJobRepo,
            patch("apps.api.routes.jobs.RunRepository") as MockRunRepo,
        ):
            MockJobRepo.return_value.get.return_value = job
            MockRunRepo.return_value.get.return_value = run_b
            resp = client_b.get("/api/app/jobs/job-bbb")

        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        assert resp.json()["id"] == "job-bbb"


# ---------------------------------------------------------------------------
# Phase 7D-3: FitReport isolation
# ---------------------------------------------------------------------------


class TestFitReportIsolation:
    def test_cross_workspace_fit_report_returns_403(self, client_b: TestClient):
        """GET /api/app/fit-reports/{id} — fit_report.workspace_id = ws_a, requester ws_b → 403."""
        rpt_a = _fit_report("rpt-aaa", workspace_id=WS_A)

        with patch("apps.api.routes.reports.FitReportRepository") as MockRepo:
            MockRepo.return_value.get.return_value = rpt_a
            resp = client_b.get("/api/app/fit-reports/rpt-aaa")

        assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"

    def test_nonexistent_fit_report_returns_404(self, client_b: TestClient):
        """GET /api/app/fit-reports/{id} — not found → 404."""
        with patch("apps.api.routes.reports.FitReportRepository") as MockRepo:
            MockRepo.return_value.get.return_value = None
            resp = client_b.get("/api/app/fit-reports/does-not-exist")

        assert resp.status_code == 404

    def test_same_workspace_fit_report_returns_200(self, client_b: TestClient):
        """GET /api/app/fit-reports/{id} — fit_report.workspace_id = ws_b → 200."""
        rpt_b = _fit_report("rpt-bbb", workspace_id=WS_B)

        with patch("apps.api.routes.reports.FitReportRepository") as MockRepo:
            MockRepo.return_value.get.return_value = rpt_b
            resp = client_b.get("/api/app/fit-reports/rpt-bbb")

        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        assert resp.json()["id"] == "rpt-bbb"

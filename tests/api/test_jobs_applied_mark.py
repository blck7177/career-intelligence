"""API test: the jobs library marks rows the workspace already has an
application for (is_applied), so the user doesn't double-apply (W0-C2).

Mirrors the tracker api-test harness: override get_db + get_current_workspace,
patch repositories at the ROUTE module path, TestClient(raise_server_exceptions=False).
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

WS_ID = "ws-jobs-test"
_NOW = datetime.now(timezone.utc)


def _ws() -> SimpleNamespace:
    return SimpleNamespace(id=WS_ID, name="t", tier="beta", created_at=_NOW, updated_at=_NOW)


def _job(**over) -> SimpleNamespace:
    base = dict(
        id="job-1", canonical_url="https://ex.com/1", source_url="https://ex.com/1",
        source_type="ats", title="Risk Analyst", company="Bank", location=None,
        status="reportable", discovered_run_id="run-1", created_at=_NOW, updated_at=_NOW,
        last_seen_at=None, posted_at=None, raw_payload_json=None,
    )
    base.update(over)
    return SimpleNamespace(**base)


@pytest.fixture()
def client():
    from apps.api.dependencies.auth import get_current_workspace
    from apps.api.dependencies.db import get_db
    from apps.api.main import app

    def _mock_db():
        yield MagicMock()

    app.dependency_overrides[get_db] = _mock_db
    app.dependency_overrides[get_current_workspace] = _ws
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


def test_list_marks_applied_jobs(client):
    with patch("apps.api.routes.jobs.RunRepository") as MockRun, \
         patch("apps.api.routes.jobs.JobFavoriteRepository") as MockFav, \
         patch("apps.api.routes.jobs.JobNotInterestedRepository") as MockNI, \
         patch("apps.api.routes.jobs.JobApplicationRepository") as MockApp, \
         patch("apps.api.routes.jobs.JobRepository") as MockJob:
        MockRun.return_value.list_for_workspace.return_value = [SimpleNamespace(id="run-1")]
        MockFav.return_value.list_job_ids_for_workspace.return_value = set()
        MockNI.return_value.list_job_ids_for_workspace.return_value = set()
        MockApp.return_value.list_job_ids_for_workspace.return_value = {"job-1"}
        MockJob.return_value.list.return_value = ([_job(id="job-1"), _job(id="job-2")], 2)
        resp = client.get("/api/app/jobs")
    assert resp.status_code == 200, resp.text
    by_id = {j["id"]: j for j in resp.json()["items"]}
    assert by_id["job-1"]["is_applied"] is True
    assert by_id["job-2"]["is_applied"] is False


def test_list_excludes_manual_paste_jobs(client):
    """W1 http-audit: paste-created jobs must not leak into the discovery library."""
    with patch("apps.api.routes.jobs.RunRepository") as MockRun, \
         patch("apps.api.routes.jobs.JobFavoriteRepository") as MockFav, \
         patch("apps.api.routes.jobs.JobNotInterestedRepository") as MockNI, \
         patch("apps.api.routes.jobs.JobApplicationRepository") as MockApp, \
         patch("apps.api.routes.jobs.JobRepository") as MockJob:
        MockRun.return_value.list_for_workspace.return_value = [SimpleNamespace(id="run-1")]
        for M in (MockFav, MockNI, MockApp):
            M.return_value.list_job_ids_for_workspace.return_value = set()
        MockJob.return_value.list.return_value = ([], 0)
        resp = client.get("/api/app/jobs")
    assert resp.status_code == 200, resp.text
    _, kwargs = MockJob.return_value.list.call_args
    assert kwargs["exclude_source_types"] == ["manual_paste"]

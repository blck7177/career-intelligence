"""API tests for POST /jobs/import — XOR (url | paste) dispatch into
job_ingest_service (W1-C1). The service internals are unit-tested separately;
here we assert the route's exclusivity check + correct dispatch.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from packages.infrastructure.services.job_ingest_service import JobIngestResult

WS_ID = "ws-imp"
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


def test_url_dispatches_to_ingest_from_url(client):
    with patch(
        "apps.api.routes.jobs.ingest_from_url",
        return_value=JobIngestResult(job=_job(), created=True, jd_fetched=True),
    ) as m_url, patch("apps.api.routes.jobs.ingest_from_paste") as m_paste:
        resp = client.post(
            "/api/app/jobs/import",
            json={"url": "https://boards.greenhouse.io/acme/jobs/1"},
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["created"] is True
    m_url.assert_called_once()
    m_paste.assert_not_called()


def test_response_carries_the_employer_posting_date(client):
    """JobRead declares posted_at with a None default, so a hand-built response
    dict that omits it serves null however well the column is populated."""
    posted = datetime(2026, 7, 27, 15, 24, 58, tzinfo=timezone.utc)
    with patch(
        "apps.api.routes.jobs.ingest_from_url",
        return_value=JobIngestResult(job=_job(posted_at=posted), created=True, jd_fetched=True),
    ), patch("apps.api.routes.jobs.ingest_from_paste"):
        resp = client.post(
            "/api/app/jobs/import",
            json={"url": "https://www.acme.com/careers/post?gh_jid=6107228004"},
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["job"]["posted_at"] is not None


def test_paste_dispatches_to_ingest_from_paste(client):
    with patch("apps.api.routes.jobs.ingest_from_url") as m_url, patch(
        "apps.api.routes.jobs.ingest_from_paste",
        return_value=JobIngestResult(
            job=_job(source_type="manual_paste", canonical_url="manual://ws-imp/abc"),
            created=True, jd_fetched=True,
        ),
    ) as m_paste:
        resp = client.post(
            "/api/app/jobs/import",
            json={"company": "Acme", "title": "Risk", "jd_text": "x" * 300},
        )
    assert resp.status_code == 200, resp.text
    m_paste.assert_called_once()
    m_url.assert_not_called()


def test_both_url_and_paste_returns_422(client):
    resp = client.post(
        "/api/app/jobs/import",
        json={"url": "https://x.com/1", "company": "A", "title": "B", "jd_text": "c" * 300},
    )
    assert resp.status_code == 422


def test_neither_returns_422(client):
    resp = client.post("/api/app/jobs/import", json={})
    assert resp.status_code == 422


def test_present_but_empty_url_routes_to_url_path_400(client):
    """A present-but-empty/whitespace url is a malformed URL (→ ingest_from_url's
    400 scheme check), NOT a missing-field XOR 422. Preserves the original
    import_job behaviour. The scheme check fires before any DB access, so the
    real service runs against the MagicMock db without touching it."""
    resp = client.post("/api/app/jobs/import", json={"url": "   "})
    assert resp.status_code == 400, resp.text
    assert "http" in resp.json()["detail"].lower()

"""Unit tests for job_ingest_service (W1-C1 paste path + URL path guards).

In-memory SQLite + real ORM; the only LLM call (extract_jd_fields) is mocked.
The URL path's fetch tier is mocked at fetch_jd_from_url — what's under test
here is what the service does with a fetch result, not the fetching itself
(that lives in tests/worker/test_jd_fetch.py).
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from packages.infrastructure.db.models import Base, Job, Run
from packages.infrastructure.jd_fetch.service import JdFetchResult
from packages.infrastructure.services.job_ingest_service import (
    ingest_from_paste,
    ingest_from_url,
)

# A realistic JD: ≥200 chars, not a CSS/JS page shell → passes _validate_jd_text.
_JD = "Senior Risk Analyst\n\n" + (
    "We are looking for an experienced risk analyst to join our markets team "
    "and own counterparty exposure reporting. " * 8
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _pragma(conn, _):
        conn.execute("PRAGMA foreign_keys = OFF")

    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s
    Base.metadata.drop_all(engine)
    engine.dispose()


def _ws(id="ws-1"):
    return SimpleNamespace(id=id)


# extract_jd_fields is imported inside the function, so patch it at its source module.
def _no_llm(fn):
    fn = patch("packages.infrastructure.llm.jd_extractor.extract_jd_fields", return_value={"required_skills": ["risk"]})(fn)
    fn = patch("packages.infrastructure.llm.client.get_llm_client", lambda: object())(fn)
    fn = patch("packages.infrastructure.llm.usage_writer.set_llm_context", lambda **k: None)(fn)
    return fn


@_no_llm
def test_paste_creates_manual_job(_extract, db):
    result = ingest_from_paste(db, _ws(), company="Acme", title="Risk Analyst", jd_text=_JD)
    assert result.created is True
    assert result.jd_fetched is True
    job = result.job
    assert job.source_type == "manual_paste"
    assert job.status == "reportable"
    assert job.canonical_url.startswith("manual://ws-1/")
    assert job.source_url == job.canonical_url  # no real posting URL
    assert job.jd_text and job.company == "Acme" and job.title == "Risk Analyst"


@_no_llm
def test_paste_same_jd_same_workspace_dedups(_extract, db):
    first = ingest_from_paste(db, _ws(), company="Acme", title="Risk Analyst", jd_text=_JD)
    # Same JD text (→ same content hash) in the same workspace re-dedups, even
    # with a different title, and does NOT create a second row.
    second = ingest_from_paste(db, _ws(), company="Acme", title="Different Title", jd_text=_JD)
    assert first.created is True
    assert second.created is False
    assert second.job.id == first.job.id


@_no_llm
def test_paste_same_jd_cross_workspace_no_collision(_extract, db):
    a = ingest_from_paste(db, _ws("ws-A"), company="Acme", title="R", jd_text=_JD)
    b = ingest_from_paste(db, _ws("ws-B"), company="Acme", title="R", jd_text=_JD)
    assert a.created is True and b.created is True
    assert a.job.id != b.job.id
    assert a.job.canonical_url != b.job.canonical_url  # workspace id embedded → private


def test_paste_short_jd_rejected(db):
    with pytest.raises(HTTPException) as exc:
        ingest_from_paste(db, _ws(), company="Acme", title="R", jd_text="too short")
    assert exc.value.status_code == 422


# ---------------------------------------------------------------------------
# URL path — what the service does with a fetch result it can't build a job from
# ---------------------------------------------------------------------------

# A careers page that renders its board client-side: fetch comes back empty and
# the URL alone would yield title "Post" at company "Www".
_EMBED_URL = "https://www.kkr.com/careers/career-opportunities/post?gh_jid=6107228004"

_UNREADABLE = JdFetchResult(
    ok=False, jd_text=None, jd_hash=None,
    error="Fetched text looks like a page shell (CSS/JS), not a JD",
    source="worker_fetch", fetch_status="shell",
)

_RESOLVED = JdFetchResult(
    ok=True,
    jd_text=_JD,
    jd_hash="deadbeefdeadbeef",
    error=None,
    source="ats_api",
    fetch_status="success",
    posted_at=datetime(2026, 7, 2, 20, 0, tzinfo=timezone.utc),
    title="Quantitative Investment Risk Professional ",  # trailing space is real
    company="Careers at KKR",
    location="New York, New York, United States",
)


def _with_fetch(result):
    """Patch the fetch tier at its source module — ingest_from_url imports it
    inside the function body."""
    return patch("packages.infrastructure.jd_fetch.fetch_jd_from_url", return_value=result)


@_no_llm
def test_url_unreadable_posting_is_refused_not_stored(_extract, db):
    with _with_fetch(_UNREADABLE), pytest.raises(HTTPException) as exc:
        ingest_from_url(db, _ws(), _EMBED_URL)

    assert exc.value.status_code == 422
    # No JD *and* no title means the row would be pure URL guesswork — better
    # no row than "Post" at "Www".
    assert db.query(Job).count() == 0
    run = db.query(Run).one()
    assert run.status == "failed"
    assert run.result_summary_json["reason"] == "jd_unreadable"


@_no_llm
def test_url_refusal_can_be_retried(_extract, db):
    """tasks.idempotency_key is UNIQUE and the refused attempt still commits its
    task, so a url-keyed task would make the second try a 500."""
    for _ in range(2):
        with _with_fetch(_UNREADABLE), pytest.raises(HTTPException) as exc:
            ingest_from_url(db, _ws(), _EMBED_URL)
        assert exc.value.status_code == 422


@_no_llm
def test_url_adopts_identity_reported_by_the_ats(_extract, db):
    with _with_fetch(_RESOLVED):
        result = ingest_from_url(db, _ws(), _EMBED_URL)

    job = result.job
    assert result.created is True and result.jd_fetched is True
    assert job.title == "Quantitative Investment Risk Professional"  # stripped
    assert job.company == "Careers at KKR"  # not "Www"
    assert job.status == "reportable"
    assert job.posted_at is not None
    # Re-read from the DB: the ATS location used to be resolved and then handed
    # only to the extractor as LLM context, never passed to job_repo.create().
    db.refresh(job)
    assert job.location == "New York, New York, United States"


@_no_llm
def test_url_company_fallback_skips_the_careers_subdomain(_extract, db):
    """No ATS identity, but a readable JD — the row is kept and the company is
    guessed from the host, which must not collapse to "Www"."""
    with _with_fetch(JdFetchResult(
        ok=True, jd_text=_JD, jd_hash="cafecafecafecafe", error=None,
        source="worker_fetch", fetch_status="success",
    )):
        result = ingest_from_url(db, _ws(), "https://www.acme-corp.com/careers/senior-risk-analyst")

    assert result.job.company == "Acme Corp"
    assert result.job.title == "Senior Risk Analyst"
    # Unlike title/company there is no guess worth making for location — stay
    # NULL rather than seed the column with empty strings.
    assert result.job.location is None

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
from packages.infrastructure.llm.identity_extractor import JobIdentity
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


_SCRAPED = JdFetchResult(
    ok=True, jd_text=_JD, jd_hash="cafecafecafecafe", error=None,
    source="worker_fetch", fetch_status="success",
)
_SCRAPE_URL = "https://www.acme-corp.com/careers/senior-risk-analyst"


def _with_identity(identity):
    return patch(
        "packages.infrastructure.llm.identity_extractor.extract_job_identity",
        return_value=identity,
    )


# ---------------------------------------------------------------------------
# URL path — identity when nothing structured supplied it
# ---------------------------------------------------------------------------


@_no_llm
def test_url_identity_is_read_from_the_page_when_the_ats_is_silent(_extract, db):
    """A readable JD with no ATS/JSON-LD identity: the page is read, not the URL.

    This replaces a guess (slug -> title, hostname -> company) that produced
    rows like "169151" at "Higher" — see the refusal test below for why the
    guess is gone rather than kept as a backstop.
    """
    identity = JobIdentity(title="Senior Risk Analyst", company="Acme Corp", location="New York")
    with _with_fetch(_SCRAPED), _with_identity(identity):
        result = ingest_from_url(db, _ws(), _SCRAPE_URL)

    assert result.job.title == "Senior Risk Analyst"
    assert result.job.company == "Acme Corp"
    db.refresh(result.job)
    assert result.job.location == "New York"


@_no_llm
def test_url_without_readable_identity_is_refused_not_guessed(_extract, db):
    """The JD is readable but nothing can say what job it is.

    The old behaviour built a row anyway out of the URL string. A wrong row is
    worse than no row: it is indistinguishable in the UI from a correct one.
    """
    with _with_fetch(_SCRAPED), _with_identity(None), pytest.raises(HTTPException) as exc:
        ingest_from_url(db, _ws(), _SCRAPE_URL)

    assert exc.value.status_code == 422
    assert "title" in exc.value.detail.lower()
    assert db.query(Job).count() == 0
    run = db.query(Run).one()
    assert run.status == "failed"
    assert run.result_summary_json["reason"] == "identity_unresolved"
    # Nothing that used to be guessed leaked into the failure record either.
    assert "Senior Risk Analyst" not in str(run.result_summary_json)


@_no_llm
def test_url_keeps_company_blank_rather_than_naming_the_website(_extract, db):
    """An unbranded page yields a title and no employer. Blank is the honest
    answer; "Acme Corp" inferred from acme-corp.com is the guess we removed."""
    with _with_fetch(_SCRAPED), _with_identity(JobIdentity(title="Senior Risk Analyst")):
        result = ingest_from_url(db, _ws(), _SCRAPE_URL)

    assert result.job.title == "Senior Risk Analyst"
    assert result.job.company == ""
    db.refresh(result.job)
    assert result.job.location is None


@_no_llm
def test_url_with_ats_identity_never_calls_the_extractor(_extract, db):
    """The LLM channel is the fallback for silence, not a second opinion — a
    posting the ATS already named must not cost a call."""
    with _with_fetch(_RESOLVED), _with_identity(None) as mock_identity:
        ingest_from_url(db, _ws(), _EMBED_URL)

    mock_identity.assert_not_called()


@_no_llm
def test_url_identity_failure_does_not_fabricate(_extract, db):
    """An LLM outage degrades to a refusal, never to a URL-derived row."""
    with _with_fetch(_SCRAPED), patch(
        "packages.infrastructure.llm.identity_extractor.extract_job_identity",
        side_effect=RuntimeError("provider down"),
    ), pytest.raises(HTTPException) as exc:
        ingest_from_url(db, _ws(), _SCRAPE_URL)

    # Degrades to the refusal, not to a 500 and not to a URL-derived row.
    assert exc.value.status_code == 422
    assert db.query(Job).count() == 0


# ---------------------------------------------------------------------------
# URL path — aggregators that cannot be fetched at all
# ---------------------------------------------------------------------------


@_no_llm
@pytest.mark.parametrize(
    "url",
    [
        "https://www.linkedin.com/jobs/view/4012345678",
        "https://linkedin.com/jobs/view/4012345678",
        "https://www.indeed.com/viewjob?jk=cb4d4c846374e999&from=mcp-openai-jobsearch",
        "https://uk.indeed.com/viewjob?jk=abc123",
    ],
)
def test_blocked_aggregators_are_refused_at_the_door(_extract, db, url):
    """Verified unreachable on every tier (Indeed: 403 direct even with a
    browser UA, and the Jina renderer returns the challenge page). Telling the
    user that up front beats a generic "couldn't read this posting" after the
    fetch tiers grind through it."""
    with pytest.raises(HTTPException) as exc:
        ingest_from_url(db, _ws(), url)

    assert exc.value.status_code == 400
    # No run/task/row is created for a request that never reached the pipeline.
    assert db.query(Run).count() == 0
    assert db.query(Job).count() == 0


# ---------------------------------------------------------------------------
# URL path — the charge has to be attributable to something that exists
# ---------------------------------------------------------------------------


def _order_tracking(db, order):
    """Record the sequence of commits and LLM calls on this session."""
    real_commit = db.commit

    def tracked_commit():
        order.append("commit")
        real_commit()

    db.commit = tracked_commit
    return db


@_no_llm
def test_run_is_committed_before_any_llm_call(_extract, db):
    """The cost ledger writes from its own DB session, so a run that is only
    flushed does not exist as far as that session is concerned: the usage
    event's foreign key fails, the fire-and-forget writer swallows it, and an
    already-incurred charge is silently lost. Every manual import between
    2026-07-10 and this fix went unrecorded exactly that way.

    Ordering is the invariant — cross-session visibility can't be asserted
    against an in-memory SQLite engine, where both sessions share a connection.
    """
    order: list[str] = []
    _order_tracking(db, order)

    def _llm_marker(*_a, **_kw):
        order.append("llm")
        return JobIdentity(title="Senior Risk Analyst", company="Acme Corp")

    with _with_fetch(_SCRAPED), patch(
        "packages.infrastructure.llm.identity_extractor.extract_job_identity",
        side_effect=_llm_marker,
    ):
        ingest_from_url(db, _ws(), _SCRAPE_URL)

    assert "llm" in order, "the identity channel should have run for this fixture"
    assert order.index("commit") < order.index("llm")


@_no_llm
def test_paste_commits_the_run_before_its_llm_call(_extract, db):
    order: list[str] = []
    _order_tracking(db, order)

    def _llm_marker(*_a, **_kw):
        order.append("llm")
        return {"required_skills": []}

    with patch(
        "packages.infrastructure.llm.jd_extractor.extract_jd_fields",
        side_effect=_llm_marker,
    ):
        ingest_from_paste(db, _ws(), company="Acme", title="Analyst", jd_text=_JD)

    assert order.index("commit") < order.index("llm")


@_no_llm
def test_refused_import_still_leaves_its_run_recorded(_extract, db):
    """The early commit must not cost us the failure record: a refusal is still
    an attempt worth accounting for, and its run carries the reason."""
    with _with_fetch(_SCRAPED), _with_identity(None), pytest.raises(HTTPException):
        ingest_from_url(db, _ws(), _SCRAPE_URL)

    run = db.query(Run).one()
    assert run.status == "failed"
    assert run.result_summary_json["reason"] == "identity_unresolved"


@_no_llm
def test_lookalike_domain_is_not_blocked(_extract, db):
    """Suffix matching must not catch a different registrable domain."""
    identity = JobIdentity(title="Senior Risk Analyst", company="Not Indeed")
    with _with_fetch(_SCRAPED), _with_identity(identity):
        result = ingest_from_url(db, _ws(), "https://careers.notindeed.com/jobs/1")

    assert result.created is True

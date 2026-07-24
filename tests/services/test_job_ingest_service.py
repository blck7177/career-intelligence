"""Unit tests for job_ingest_service.ingest_from_paste (W1-C1).

In-memory SQLite + real ORM; the only LLM call (extract_jd_fields) is mocked.
The URL path is a verbatim lift of the prior import_job body (behaviour
unchanged) and is exercised through the route dispatch tests instead.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from packages.infrastructure.db.models import Base
from packages.infrastructure.services.job_ingest_service import ingest_from_paste

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

"""Tests for DOA (dead-on-arrival) detection and the dead_urls negative cache."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from packages.infrastructure.db.models import Base
from packages.infrastructure.db.repositories import DeadUrlRepository
from packages.infrastructure.jd_fetch.service import JdFetchResult, _is_closed_posting


class TestClosedPostingDetection:
    """Conservative: a short status page with a closed marker is DOA; a full JD
    that merely mentions the phrase must never be flagged."""

    def test_short_page_no_longer_accepting_is_closed(self):
        assert _is_closed_posting("This job is no longer accepting applications.")

    def test_position_filled_short(self):
        assert _is_closed_posting("Sorry — this position has been filled.")

    def test_long_jd_mentioning_marker_not_flagged(self):
        jd = "We are hiring a Market Risk Analyst. " * 100  # > 1000 chars
        jd += " Note: we are no longer accepting applications by email; use the portal."
        assert not _is_closed_posting(jd)

    def test_normal_jd_not_flagged(self):
        assert not _is_closed_posting(
            "Senior Market Risk Analyst. Responsibilities include VaR modeling..."
        )

    def test_empty_not_flagged(self):
        assert not _is_closed_posting("")


class TestJdFetchResultHttpStatus:
    def test_http_status_defaults_none(self):
        r = JdFetchResult(
            ok=True, jd_text="x", jd_hash="h", error=None,
            source="worker_fetch", fetch_status="success",
        )
        assert r.http_status is None

    def test_http_status_settable(self):
        r = JdFetchResult(
            ok=False, jd_text=None, jd_hash=None, error="gone",
            source="worker_fetch", fetch_status="doa", http_status=404,
        )
        assert r.http_status == 404


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s
    Base.metadata.drop_all(engine)
    engine.dispose()


class TestDeadUrlRepository:
    def test_record_then_is_dead(self, session):
        repo = DeadUrlRepository(session)
        url = "https://co.com/job/1"
        assert not repo.is_dead(url)
        repo.record(url=url, reason="http_404", http_status=404)
        assert repo.is_dead(url)

    def test_record_idempotent_bumps_times_seen(self, session):
        repo = DeadUrlRepository(session)
        url = "https://co.com/job/2"
        d1 = repo.record(url=url, reason="http_410", http_status=410)
        assert d1.times_seen == 1
        d2 = repo.record(url=url, reason="http_410", http_status=410)
        assert d2.times_seen == 2
        assert d1.id == d2.id  # same row, not a duplicate

    def test_touch_bumps_existing(self, session):
        repo = DeadUrlRepository(session)
        url = "https://co.com/job/3"
        repo.record(url=url, reason="closed_posting", http_status=200)
        repo.touch(url)
        assert repo.is_dead(url)

    def test_domain_extracted(self, session):
        repo = DeadUrlRepository(session)
        d = repo.record(
            url="https://boards.greenhouse.io/co/jobs/1", reason="http_404", http_status=404
        )
        assert d.domain == "boards.greenhouse.io"

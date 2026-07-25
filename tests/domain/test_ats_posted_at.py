"""W7-C1 — posted_at capture from ATS board responses. Each provider exposes the
employer posting date differently (Greenhouse ISO first_published/updated_at,
Lever epoch-ms createdAt, Ashby ISO publishedAt); absent/garbage → None, never
fabricated."""
from __future__ import annotations

from datetime import datetime, timezone

from packages.domain.agent_jobs.ats_providers import (
    _parse_ats_epoch_ms,
    _parse_ats_iso,
    parse_board_response,
)


def test_greenhouse_prefers_first_published_over_updated_at():
    data = {"jobs": [{
        "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
        "title": "Risk Analyst", "company_name": "Acme",
        "first_published": "2026-06-01T12:00:00-04:00",
        "updated_at": "2026-06-20T09:00:00-04:00",
    }]}
    [bj] = parse_board_response("greenhouse", data)
    assert bj.posted_at == datetime(2026, 6, 1, 16, 0, tzinfo=timezone.utc)


def test_greenhouse_falls_back_to_updated_at():
    data = {"jobs": [{
        "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
        "title": "T", "company_name": "Acme",
        "updated_at": "2026-06-20T09:00:00+00:00",
    }]}
    [bj] = parse_board_response("greenhouse", data)
    assert bj.posted_at == datetime(2026, 6, 20, 9, 0, tzinfo=timezone.utc)


def test_greenhouse_missing_date_is_none():
    data = {"jobs": [{"absolute_url": "https://x/1", "title": "T", "company_name": "C"}]}
    [bj] = parse_board_response("greenhouse", data)
    assert bj.posted_at is None


def test_lever_parses_epoch_ms():
    data = [{"hostedUrl": "https://jobs.lever.co/acme/1", "text": "T", "createdAt": 1_717_200_000_000}]
    [bj] = parse_board_response("lever", data)
    assert bj.posted_at == datetime.fromtimestamp(1_717_200_000, tz=timezone.utc)


def test_lever_missing_created_at_is_none():
    [bj] = parse_board_response("lever", [{"hostedUrl": "https://jobs.lever.co/acme/1", "text": "T"}])
    assert bj.posted_at is None


def test_ashby_parses_iso_z():
    data = {"jobs": [{
        "jobUrl": "https://jobs.ashbyhq.com/acme/1", "title": "T",
        "descriptionPlain": "x", "publishedAt": "2026-05-20T00:00:00Z",
    }]}
    [bj] = parse_board_response("ashby", data)
    assert bj.posted_at == datetime(2026, 5, 20, 0, 0, tzinfo=timezone.utc)


def test_iso_helper_garbage_and_types():
    assert _parse_ats_iso("not-a-date") is None
    assert _parse_ats_iso(None) is None
    assert _parse_ats_iso(12345) is None
    # naive ISO is treated as UTC
    assert _parse_ats_iso("2026-01-02T03:04:05") == datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


def test_epoch_helper_rejects_non_numbers_and_bool():
    assert _parse_ats_epoch_ms("1717200000000") is None
    assert _parse_ats_epoch_ms(None) is None
    assert _parse_ats_epoch_ms(True) is None  # bool is not a valid epoch
    assert _parse_ats_epoch_ms(1_717_200_000_000) == datetime.fromtimestamp(1_717_200_000, tz=timezone.utc)

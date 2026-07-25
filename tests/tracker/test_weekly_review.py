"""Wave 5 — weekly review: pure aggregation, LLM-mock persistence, the degrade
path (LLM failure → NULL narrative), and beat idempotency (upsert per week)."""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from packages.contracts.api.applications import PlannerSettings
from packages.domain.planner.rules import ActionView, ApplicationView, EventView
from packages.domain.planner.weekly import build_weekly_stats
from packages.infrastructure.db.repositories import (
    JobApplicationRepository,
    PlannerReviewRepository,
    WorkspaceRepository,
)
from packages.infrastructure.llm.client import LLMCallError
from packages.infrastructure.services import weekly_review_service

# America/New_York (default tz): 12:00 UTC = 08:00 local → the local date is the
# same calendar day, so these all fall in the week starting Mon 2026-07-13.
WEEK_START = date(2026, 7, 13)  # Monday
NOW = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)  # Sunday of that week
IN_WEEK = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)  # Wednesday
LAST_WEEK = datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc)


def _done(type_: str, at: datetime) -> ActionView:
    return ActionView(type=type_, status="done", auto_generated=True, completed_at=at)


def test_build_weekly_stats_counts_triplet_lanes_channels_and_conversion():
    settings = PlannerSettings()
    apps = [
        # Applied this week, referral, lane A; did a follow-up + outreach this
        # week; got an interview → counts toward reached_interview.
        ApplicationView(
            id="a1", status="applied", applied_at=IN_WEEK, created_at=LAST_WEEK,
            lane="a", channel="referral",
            events=[EventView(event_type="interview_scheduled", created_at=IN_WEEK, round_type="phone")],
            actions=[_done("follow_up", IN_WEEK), _done("networking", IN_WEEK)],
        ),
        # Still just planned — not an "applied" for the denominator.
        ApplicationView(id="a2", status="planned", applied_at=None, created_at=IN_WEEK, lane="b"),
        # Offer, applied last week — applied_total but its applied_at is out of
        # the this-week window, so it does NOT count in `applied`.
        ApplicationView(id="a3", status="offer", applied_at=LAST_WEEK, created_at=LAST_WEEK),
    ]

    stats = build_weekly_stats(apps, settings, WEEK_START, NOW)

    assert stats.week_start == "2026-07-13"
    assert stats.applied == 1  # only a1 applied within the week
    assert stats.outreach == 1  # a1's completed networking
    assert stats.follow_ups == 1  # a1's completed follow_up
    assert stats.by_lane == {"a": 1, "b": 1, "c": 0, "none": 1}
    assert stats.by_channel == {"referral": 1, "unknown": 2}
    # Conversion: a1 (interview event) + a3 (offer status) reached interview;
    # both count as applied_total → 2/2.
    assert stats.applied_total == 2
    assert stats.reached_interview == 2
    assert stats.interview_rate == 1.0
    assert stats.replies_are_manual is True
    # Funnel is the shared stage set.
    assert [s.key for s in stats.funnel] == [
        "planned", "applied", "in_review", "interviewing", "onsite", "offer",
    ]


def test_build_weekly_stats_zero_applies_is_safe():
    stats = build_weekly_stats([], PlannerSettings(), WEEK_START, NOW)
    assert stats.applied == 0
    assert stats.applied_total == 0
    assert stats.interview_rate == 0.0  # no ZeroDivisionError


def test_build_weekly_stats_counts_global_actions_in_triplet():
    """Standalone (application_id-NULL) networking/follow_up to-dos count toward
    outreach/follow_ups too — matching PlannerStats' app-filter-less SQL count."""
    settings = PlannerSettings()
    apps = [ApplicationView(id="a1", status="applied", applied_at=IN_WEEK, created_at=LAST_WEEK)]
    globals_ = [_done("networking", IN_WEEK), _done("follow_up", IN_WEEK), _done("networking", LAST_WEEK)]

    stats = build_weekly_stats(apps, settings, WEEK_START, NOW, global_actions=globals_)

    assert stats.outreach == 1  # in-week global networking (LAST_WEEK one excluded)
    assert stats.follow_ups == 1  # in-week global follow_up


class _FakeLLM:
    def __init__(self, text=None, error=False):
        self._text = text
        self._error = error
        self.calls = 0

    def complete_simple(self, system_prompt, user_prompt, **kwargs):
        self.calls += 1
        if self._error:
            raise LLMCallError("boom")
        return self._text


def _seed_one_applied(session, ws_id):
    WorkspaceRepository(session).create(name="t", workspace_id=ws_id)
    JobApplicationRepository(session).create(
        workspace_id=ws_id, job_id="j1", status="applied", applied_at=IN_WEEK, lane="a"
    )
    session.flush()


def test_generate_weekly_review_persists_stats_and_narrative(db_session, monkeypatch):
    _seed_one_applied(db_session, "ws1")
    fake = _FakeLLM(text="Solid week — one application in. Keep the outreach going.")
    monkeypatch.setattr(weekly_review_service, "get_llm_client", lambda: fake)

    row = weekly_review_service.generate_weekly_review(
        db_session, "ws1", now_utc=NOW, week_start=WEEK_START
    )

    assert fake.calls == 1
    assert row is not None
    assert row.narrative_md.startswith("Solid week")
    assert row.stats_json["week_start"] == "2026-07-13"
    assert row.stats_json["applied"] == 1
    # Round-trips through the repo.
    latest = PlannerReviewRepository(db_session).get_latest("ws1")
    assert latest.id == row.id


def test_generate_weekly_review_degrades_on_llm_error(db_session, monkeypatch):
    _seed_one_applied(db_session, "ws2")
    monkeypatch.setattr(weekly_review_service, "get_llm_client", lambda: _FakeLLM(error=True))

    row = weekly_review_service.generate_weekly_review(
        db_session, "ws2", now_utc=NOW, week_start=WEEK_START
    )

    assert row is not None
    assert row.narrative_md is None  # degraded to number-only template
    assert row.stats_json["applied"] == 1  # stats still computed + stored


def test_generate_weekly_review_degrades_on_non_llm_error(db_session, monkeypatch):
    """A malformed response can raise IndexError OUTSIDE the client's LLMCallError
    guard; the best-effort narrative must still degrade (not abort the sweep)."""
    _seed_one_applied(db_session, "ws2b")

    class _Boom:
        def complete_simple(self, *a, **k):
            raise IndexError("list index out of range")  # empty choices, etc.

    monkeypatch.setattr(weekly_review_service, "get_llm_client", lambda: _Boom())
    row = weekly_review_service.generate_weekly_review(
        db_session, "ws2b", now_utc=NOW, week_start=WEEK_START
    )
    assert row is not None
    assert row.narrative_md is None  # degraded, did not propagate


def test_generate_weekly_review_empty_narrative_is_none(db_session, monkeypatch):
    _seed_one_applied(db_session, "ws3")
    monkeypatch.setattr(weekly_review_service, "get_llm_client", lambda: _FakeLLM(text="   "))
    row = weekly_review_service.generate_weekly_review(
        db_session, "ws3", now_utc=NOW, week_start=WEEK_START
    )
    assert row.narrative_md is None  # whitespace-only → treated as no narrative


def test_generate_weekly_review_upserts_same_week(db_session, monkeypatch):
    _seed_one_applied(db_session, "ws4")
    monkeypatch.setattr(weekly_review_service, "get_llm_client", lambda: _FakeLLM(text="v1"))
    r1 = weekly_review_service.generate_weekly_review(
        db_session, "ws4", now_utc=NOW, week_start=WEEK_START
    )
    monkeypatch.setattr(weekly_review_service, "get_llm_client", lambda: _FakeLLM(text="v2"))
    r2 = weekly_review_service.generate_weekly_review(
        db_session, "ws4", now_utc=NOW, week_start=WEEK_START
    )

    assert r1.id == r2.id  # same (workspace, week) row, updated in place
    assert r2.narrative_md == "v2"


def test_run_weekly_review_once_defaults_to_local_week(db_session, monkeypatch):
    from apps.worker.tasks import planner_run

    _seed_one_applied(db_session, "ws5")
    monkeypatch.setattr(weekly_review_service, "get_llm_client", lambda: _FakeLLM(text="ok"))

    result = planner_run.run_weekly_review_once(db_session, NOW)

    assert result == {"workspaces": 1, "reviews_generated": 1}
    latest = PlannerReviewRepository(db_session).get_latest("ws5")
    # NOW is Sun 2026-07-19; local (NY) Monday of that week is 2026-07-13.
    assert latest.week_start == WEEK_START


def test_week_start_for_picks_finished_week_across_timezones():
    """At the beat's real fire instant (Mon 02:00 UTC), both an Americas zone
    (local still Sunday) and a non-Americas zone (local already Monday) must
    resolve to the SAME just-finished week's Monday — never the empty new week."""
    fire = datetime(2026, 7, 20, 2, 0, tzinfo=timezone.utc)  # Monday 02:00 UTC
    ny = weekly_review_service._week_start_for(fire, "America/New_York")
    london = weekly_review_service._week_start_for(fire, "Europe/London")
    tokyo = weekly_review_service._week_start_for(fire, "Asia/Tokyo")
    assert ny == date(2026, 7, 13)  # week Mon 7/13..Sun 7/19 (just finished)
    assert london == date(2026, 7, 13)  # NOT 7/20 (the brand-new week)
    assert tokyo == date(2026, 7, 13)


def test_planner_review_repo_get_latest_picks_newest_week(db_session):
    repo = PlannerReviewRepository(db_session)
    repo.upsert(workspace_id="ws6", week_start=date(2026, 7, 6), stats_json={"a": 1}, narrative_md="old")
    repo.upsert(workspace_id="ws6", week_start=date(2026, 7, 13), stats_json={"a": 2}, narrative_md="new")
    db_session.flush()
    assert repo.get_latest("ws6").week_start == date(2026, 7, 13)

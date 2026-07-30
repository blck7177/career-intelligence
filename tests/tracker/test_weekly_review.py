"""Wave 5 — weekly review: pure aggregation, LLM-mock persistence, the degrade
path (LLM failure → NULL narrative), and beat idempotency (upsert per week)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

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


# --- read state (V5-C2) ------------------------------------------------------

READ_AT = datetime(2026, 7, 20, 9, 0, tzinfo=timezone.utc)


def _utc(dt):
    """The test DB is SQLite, which drops tzinfo on round-trip; postgres keeps it.
    Normalise so these assertions are about the instant, not the driver."""
    return dt if dt is None or dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def test_mark_read_stamps_once_and_is_idempotent(db_session):
    """The banner's button invites a double-click, and the first time you saw a
    review is the fact worth keeping — so a repeat must not slide the timestamp
    forward."""
    repo = PlannerReviewRepository(db_session)
    repo.upsert(workspace_id="ws7", week_start=WEEK_START, stats_json={"a": 1}, narrative_md="n")
    db_session.flush()
    assert repo.get_for_week("ws7", WEEK_START).read_at is None

    first = repo.mark_read("ws7", WEEK_START, now_utc=READ_AT)
    assert _utc(first.read_at) == READ_AT

    again = repo.mark_read("ws7", WEEK_START, now_utc=READ_AT + timedelta(hours=5))
    assert _utc(again.read_at) == READ_AT


def test_mark_read_is_workspace_scoped(db_session):
    """Another workspace's week must be indistinguishable from a week that does
    not exist — the route turns both into 404."""
    repo = PlannerReviewRepository(db_session)
    repo.upsert(workspace_id="ws8", week_start=WEEK_START, stats_json={"a": 1}, narrative_md="n")
    db_session.flush()

    assert repo.mark_read("ws9-other", WEEK_START, now_utc=READ_AT) is None
    assert repo.mark_read("ws8", date(2026, 6, 1), now_utc=READ_AT) is None
    # ...and the real row was not touched by either miss.
    assert repo.get_for_week("ws8", WEEK_START).read_at is None


def test_reworded_narrative_keeps_read_state(db_session):
    """THE production case. The narrative comes from a model with no temperature
    or seed pinned, so a re-run for the same week produces the same numbers in
    different words. Treating that as new information would re-nag on every
    regeneration and train the user to swat the banner without looking.

    (An earlier version compared narrative text, which made the "identical
    re-run" branch unreachable in production — this test used byte-identical
    prose and so proved nothing.)"""
    repo = PlannerReviewRepository(db_session)
    repo.upsert(workspace_id="ws10", week_start=WEEK_START, stats_json={"a": 1},
                narrative_md="You applied to six roles this week.")
    repo.mark_read("ws10", WEEK_START, now_utc=READ_AT)

    repo.upsert(workspace_id="ws10", week_start=WEEK_START, stats_json={"a": 1},
                narrative_md="Six applications went out this week.")
    assert _utc(repo.get_for_week("ws10", WEEK_START).read_at) == READ_AT


def test_losing_the_narrative_does_not_re_nag(db_session):
    """A re-run whose LLM call degraded says nothing new — the user already read
    the prose. Only prose ARRIVING is new information."""
    repo = PlannerReviewRepository(db_session)
    repo.upsert(workspace_id="ws12", week_start=WEEK_START, stats_json={"a": 1}, narrative_md="prose")
    repo.mark_read("ws12", WEEK_START, now_utc=READ_AT)

    repo.upsert(workspace_id="ws12", week_start=WEEK_START, stats_json={"a": 1}, narrative_md=None)
    assert _utc(repo.get_for_week("ws12", WEEK_START).read_at) == READ_AT


def test_changed_regeneration_reopens_the_review(db_session):
    """The commonest regeneration is a retry after the LLM degraded: the user read
    a numbers-only card and the narrative arrived afterwards. Staying "read" would
    bury exactly what the retry produced."""
    repo = PlannerReviewRepository(db_session)
    repo.upsert(workspace_id="ws11", week_start=WEEK_START, stats_json={"a": 1}, narrative_md=None)
    repo.mark_read("ws11", WEEK_START, now_utc=READ_AT)

    repo.upsert(workspace_id="ws11", week_start=WEEK_START, stats_json={"a": 1}, narrative_md="arrived")
    assert repo.get_for_week("ws11", WEEK_START).read_at is None

    # Changed numbers count too, not just a changed narrative.
    repo.mark_read("ws11", WEEK_START, now_utc=READ_AT)
    repo.upsert(workspace_id="ws11", week_start=WEEK_START, stats_json={"a": 2}, narrative_md="arrived")
    assert repo.get_for_week("ws11", WEEK_START).read_at is None


# --- plan versus actual (V6-C3) ---------------------------------------------


def test_weekly_days_omit_the_days_the_ritual_never_ran(db_session):
    """Absent, not zero-filled. "Did not plan" and "planned nothing" are
    different facts, and a week padded with zeroes reads as a bad week rather
    than an unrecorded one — which is the opposite of what a gentle review is
    for."""
    from packages.domain.planner.weekly import DayLogView, build_weekly_stats

    logs = [
        DayLogView(local_date=WEEK_START, committed_est=90, done_est=60),
        DayLogView(local_date=WEEK_START + timedelta(days=2), committed_est=45, done_est=None),
    ]
    stats = build_weekly_stats(
        [], PlannerSettings(), WEEK_START, NOW, global_actions=[], day_logs=logs
    )
    assert [d.date for d in stats.days] == [
        WEEK_START.isoformat(),
        (WEEK_START + timedelta(days=2)).isoformat(),
    ]
    assert (stats.days[0].committed_est, stats.days[0].done_est) == (90, 60)
    # Planned but never closed: done_est stays None rather than becoming 0.
    assert stats.days[1].done_est is None


def test_weekly_days_are_clipped_to_the_reviewed_week_and_sorted(db_session):
    """The caller queries a range, but the aggregate is the authority on which
    week it describes — a log from the next week leaking in would be attributed
    to the wrong review."""
    from packages.domain.planner.weekly import DayLogView, build_weekly_stats

    logs = [
        DayLogView(local_date=WEEK_START + timedelta(days=3), committed_est=30),
        DayLogView(local_date=WEEK_START - timedelta(days=1), committed_est=30),  # before
        DayLogView(local_date=WEEK_START + timedelta(days=7), committed_est=30),  # after
        DayLogView(local_date=WEEK_START, committed_est=30),
    ]
    stats = build_weekly_stats(
        [], PlannerSettings(), WEEK_START, NOW, global_actions=[], day_logs=logs
    )
    assert [d.date for d in stats.days] == [
        WEEK_START.isoformat(),
        (WEEK_START + timedelta(days=3)).isoformat(),
    ]


def test_weekly_days_default_to_empty_when_no_logs_exist(db_session):
    """Every review generated before V6 has no day logs at all; the field has to
    degrade to an empty list, not None or a crash."""
    from packages.domain.planner.weekly import build_weekly_stats

    stats = build_weekly_stats([], PlannerSettings(), WEEK_START, NOW, global_actions=[])
    assert stats.days == []

"""Unit tests for the pure week-strip builder (V3-C1). No DB.

The interesting behaviour is all at the day boundary: a strip that disagrees
with the Today query about which day something falls on is worse than no strip.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from packages.contracts.api.applications import PlannerSettings
from packages.domain.planner.week import (
    InterviewSlot,
    build_week,
    week_bounds_utc,
    week_start_for,
)

# Wed 2026-07-15 12:00 UTC = 08:00 EDT, local date 2026-07-15.
NOW = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
NY = "America/New_York"


def _settings(**over) -> PlannerSettings:
    return PlannerSettings(**over)


def _slot(at: datetime, company: str = "Stripe", round_type: str | None = None) -> InterviewSlot:
    return InterviewSlot(application_id="a1", company=company, at=at, round_type=round_type)


def _build(**over):
    kwargs = dict(interviews=[], due_ats=[], settings=_settings(), now_utc=NOW)
    kwargs.update(over)
    return build_week(**kwargs)


def test_week_start_is_monday():
    assert week_start_for(date(2026, 7, 15)) == date(2026, 7, 13)  # Wed -> Mon
    assert week_start_for(date(2026, 7, 13)) == date(2026, 7, 13)  # Mon -> itself
    assert week_start_for(date(2026, 7, 19)) == date(2026, 7, 13)  # Sun -> that Mon


def test_seven_days_monday_first_with_today_marked():
    week = _build()
    assert week["week_start"] == "2026-07-13"
    assert [d["date"] for d in week["days"]] == [
        "2026-07-13", "2026-07-14", "2026-07-15",
        "2026-07-16", "2026-07-17", "2026-07-18", "2026-07-19",
    ]
    assert [d["is_today"] for d in week["days"]] == [False, False, True, False, False, False, False]


def test_rest_days_come_from_settings():
    week = _build()  # default rest_days = sat, sun
    assert [d["is_rest"] for d in week["days"]] == [False] * 5 + [True, True]
    midweek = _build(settings=_settings(rest_days=["wed"]))
    assert [d["is_rest"] for d in midweek["days"]] == [False, False, True, False, False, False, False]


def test_interview_lands_on_its_local_day_not_its_utc_day():
    """23:30 UTC Thursday is 19:30 Thursday in New York — the same day there. The
    strip must speak the user's calendar, not the server's."""
    at = datetime(2026, 7, 16, 23, 30, tzinfo=timezone.utc)
    week = _build(interviews=[_slot(at)])
    days = {d["date"]: d for d in week["days"]}
    assert len(days["2026-07-16"]["interviews"]) == 1
    assert days["2026-07-17"]["interviews"] == []


def test_interview_crossing_midnight_lands_on_the_previous_local_day():
    """02:00 UTC Friday is 22:00 Thursday in New York."""
    at = datetime(2026, 7, 17, 2, 0, tzinfo=timezone.utc)
    week = _build(interviews=[_slot(at)])
    days = {d["date"]: d for d in week["days"]}
    assert len(days["2026-07-16"]["interviews"]) == 1
    assert days["2026-07-17"]["interviews"] == []


def test_same_instant_moves_day_with_the_timezone():
    at = datetime(2026, 7, 17, 2, 0, tzinfo=timezone.utc)
    ny = _build(interviews=[_slot(at)])
    tokyo = _build(interviews=[_slot(at)], settings=_settings(timezone="Asia/Tokyo"))
    ny_days = {d["date"]: len(d["interviews"]) for d in ny["days"]}
    tk_days = {d["date"]: len(d["interviews"]) for d in tokyo["days"]}
    assert ny_days["2026-07-16"] == 1  # Thu evening in New York
    assert tk_days["2026-07-17"] == 1  # Fri morning in Tokyo


def test_interviews_sorted_within_a_day_and_carry_their_round():
    late = _slot(datetime(2026, 7, 16, 20, 0, tzinfo=timezone.utc), "Jane Street", "onsite")
    early = _slot(datetime(2026, 7, 16, 14, 0, tzinfo=timezone.utc), "Stripe", "phone")
    week = _build(interviews=[late, early])
    day = {d["date"]: d for d in week["days"]}["2026-07-16"]
    assert [i["company"] for i in day["interviews"]] == ["Stripe", "Jane Street"]
    assert [i["round_type"] for i in day["interviews"]] == ["phone", "onsite"]


def test_out_of_week_items_are_dropped_not_clamped():
    """Clamping into an edge day would overstate that day's load."""
    before = datetime(2026, 7, 10, 15, 0, tzinfo=timezone.utc)
    after = datetime(2026, 7, 25, 15, 0, tzinfo=timezone.utc)
    week = _build(interviews=[_slot(before), _slot(after)], due_ats=[before, after])
    assert sum(len(d["interviews"]) for d in week["days"]) == 0
    assert sum(d["due_count"] for d in week["days"]) == 0


def test_due_counts_bucket_by_local_day():
    tue = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)
    week = _build(due_ats=[tue, tue, datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)])
    counts = {d["date"]: d["due_count"] for d in week["days"]}
    assert counts["2026-07-14"] == 2
    assert counts["2026-07-16"] == 1
    assert counts["2026-07-13"] == 0


def test_naive_datetimes_are_read_as_utc():
    # SQLite round-trips drop tzinfo; treating those as local would shift days.
    naive = datetime(2026, 7, 16, 23, 30)
    week = _build(interviews=[_slot(naive)], due_ats=[naive])
    days = {d["date"]: d for d in week["days"]}
    assert len(days["2026-07-16"]["interviews"]) == 1
    assert days["2026-07-16"]["due_count"] == 1


def test_explicit_week_start_overrides_today():
    week = _build(week_start=date(2026, 7, 6))
    assert week["week_start"] == "2026-07-06"
    assert all(d["is_today"] is False for d in week["days"])  # today isn't in it


def test_week_bounds_are_local_midnight_to_local_midnight():
    start, end = week_bounds_utc(date(2026, 7, 13), NY)
    assert start == datetime(2026, 7, 13, 4, 0, tzinfo=timezone.utc)  # 00:00 EDT
    assert end == datetime(2026, 7, 20, 4, 0, tzinfo=timezone.utc)
    assert end - start == timedelta(days=7)


def test_dst_weeks_are_seven_local_days_not_168_hours():
    """A week is seven local midnights, so the clock change makes it 167 or 169
    hours long. Computing the end as start + 7 days would look right all year
    and silently shift the last day of exactly the two weeks that change."""
    spring_start, spring_end = week_bounds_utc(date(2026, 3, 2), NY)  # DST begins Sun 03-08
    assert (spring_end - spring_start) == timedelta(hours=167)
    autumn_start, autumn_end = week_bounds_utc(date(2026, 10, 26), NY)  # DST ends Sun 11-01
    assert (autumn_end - autumn_start) == timedelta(hours=169)


def test_interview_on_the_dst_shift_day_stays_on_that_day():
    # 05:30 UTC on the spring-forward Sunday is 00:30 EST, still that Sunday.
    at = datetime(2026, 3, 8, 5, 30, tzinfo=timezone.utc)
    week = build_week(
        interviews=[_slot(at)],
        due_ats=[at],
        settings=_settings(),
        now_utc=datetime(2026, 3, 4, 12, 0, tzinfo=timezone.utc),
        week_start=date(2026, 3, 2),
    )
    days = {d["date"]: d for d in week["days"]}
    assert len(days["2026-03-08"]["interviews"]) == 1
    assert days["2026-03-08"]["due_count"] == 1

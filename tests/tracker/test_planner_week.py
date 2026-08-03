"""Unit tests for the pure week-strip builder (V3-C1). No DB.

The interesting behaviour is all at the day boundary: a strip that disagrees
with the Today query about which day something falls on is worse than no strip.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from packages.contracts.api.applications import PlannerSettings
from packages.domain.planner.week import (
    DueItem,
    InterviewSlot,
    ScheduledBlock,
    build_week,
    contains,
    due_query_start_utc,
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


def _due(at: datetime, type_: str = "follow_up", est: int | None = None) -> DueItem:
    return DueItem(at=at, type=type_, est_minutes=est)


def _build(**over):
    # due_ats= is accepted as shorthand for bare instants, so the day-boundary
    # tests stay about boundaries rather than about estimate plumbing.
    if "due_ats" in over:
        over["due_items"] = [_due(x) for x in over.pop("due_ats")]
    kwargs = dict(interviews=[], due_items=[], settings=_settings(), now_utc=NOW)
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


def test_carried_work_lands_on_today_so_the_strip_matches_the_capacity_bar():
    """Overdue and undated to-dos are today's load — the capacity bar below the
    strip counts them, and a strip showing zero against a bar showing three
    contradicts itself on one screen."""
    week = _build(carried_into_today=3)
    counts = {d["date"]: d["due_count"] for d in week["days"]}
    assert counts["2026-07-15"] == 3  # today
    assert sum(v for k, v in counts.items() if k != "2026-07-15") == 0


def test_carried_work_adds_to_todays_own_dues():
    today_due = datetime(2026, 7, 15, 4, 0, tzinfo=timezone.utc)
    week = _build(due_ats=[today_due], carried_into_today=2)
    counts = {d["date"]: d["due_count"] for d in week["days"]}
    assert counts["2026-07-15"] == 3


def test_due_counting_starts_at_today_so_overdue_work_is_not_counted_twice():
    """A to-do due Tuesday and still pending is owed TODAY (Wednesday). If the
    per-day range still began on Monday it would show a dot on Tuesday *and* be
    added to today's carried count — two dots for one task."""
    monday, wednesday = date(2026, 7, 13), date(2026, 7, 15)
    assert due_query_start_utc(monday, wednesday, NY) == datetime(
        2026, 7, 15, 4, 0, tzinfo=timezone.utc
    )  # today's local midnight, not Monday's


def test_due_counting_starts_at_week_start_for_a_week_without_today():
    """A historical or forward week is a plain report of what fell due then."""
    past_monday, wednesday = date(2026, 7, 6), date(2026, 7, 15)
    assert due_query_start_utc(past_monday, wednesday, NY) == datetime(
        2026, 7, 6, 4, 0, tzinfo=timezone.utc
    )


def test_contains_is_a_half_open_week():
    monday = date(2026, 7, 13)
    assert contains(monday, monday)
    assert contains(monday, date(2026, 7, 19))  # Sunday
    assert not contains(monday, date(2026, 7, 20))  # next Monday
    assert not contains(monday, date(2026, 7, 12))


def test_carried_work_is_dropped_when_the_week_excludes_today():
    # Browsing a past week: there is no cell for a backlog to land on.
    week = _build(week_start=date(2026, 7, 6), carried_into_today=5)
    assert sum(d["due_count"] for d in week["days"]) == 0


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
        due_items=[_due(at)],
        settings=_settings(),
        now_utc=datetime(2026, 3, 4, 12, 0, tzinfo=timezone.utc),
        week_start=date(2026, 3, 2),
    )
    days = {d["date"]: d for d in week["days"]}
    assert len(days["2026-03-08"]["interviews"]) == 1
    assert days["2026-03-08"]["due_count"] == 1


def test_interview_duration_rides_through_to_the_day():
    # The week grid draws a block whose HEIGHT is the duration, so this value
    # has to survive the trip; before it existed the grid had nothing to size
    # blocks by and the mockup faked it with a hardcoded number.
    at = datetime(2026, 7, 16, 18, 0, tzinfo=timezone.utc)
    slot = InterviewSlot(application_id="a1", company="Stripe", at=at, duration_minutes=120)
    out = _build(interviews=[slot])
    day = next(d for d in out["days"] if d["interviews"])
    assert day["interviews"][0]["duration_minutes"] == 120


def test_a_round_logged_before_durations_existed_says_unknown_not_zero():
    # None and 0 are different claims: "we don't know how long" versus "it takes
    # no time". Rendering the second would show a day with room it does not have.
    at = datetime(2026, 7, 16, 18, 0, tzinfo=timezone.utc)
    out = _build(interviews=[InterviewSlot(application_id="a1", company="Stripe", at=at)])
    day = next(d for d in out["days"] if d["interviews"])
    assert day["interviews"][0]["duration_minutes"] is None


# --- per-day load (W0: what the taller strip renders) ------------------------


def test_due_minutes_use_the_per_type_default_never_a_raw_sum():
    # est_minutes is nullable by design. A raw column sum would read NULL as
    # zero and file a full day as an empty one.
    tue = datetime(2026, 7, 14, 16, 0, tzinfo=timezone.utc)
    week = _build(due_items=[
        _due(tue, "apply"),              # NULL -> default 5
        _due(tue, "follow_up", est=25),  # explicit wins
    ])
    day = next(d for d in week["days"] if d["date"] == "2026-07-14")
    assert day["due_count"] == 2
    assert day["due_est_minutes"] == 30


def test_todays_minutes_fold_in_the_backlog_exactly_as_the_count_does():
    # The strip sits directly above the capacity bar, which counts overdue and
    # undated work as today's load. A count that included the backlog while the
    # minutes did not would put two contradictory readings of today on one row.
    today_due = datetime(2026, 7, 15, 16, 0, tzinfo=timezone.utc)
    week = _build(
        due_items=[_due(today_due, "follow_up", est=15)],
        carried_into_today=2,
        carried_est_minutes=80,
    )
    day = next(d for d in week["days"] if d["is_today"])
    assert day["due_count"] == 3
    assert day["due_est_minutes"] == 95


def test_a_backlog_with_no_day_to_land_on_is_ignored_in_both_units():
    # A historical week has no "today" to inherit it; the count already worked
    # this way and the minutes must not diverge.
    week = _build(week_start=date(2026, 7, 6), carried_into_today=2, carried_est_minutes=80)
    assert all(d["due_est_minutes"] == 0 for d in week["days"])
    assert all(d["due_count"] == 0 for d in week["days"])


def test_scheduled_minutes_are_separate_from_owed_minutes():
    # A to-do due Friday but scheduled Wednesday belongs to both days, counted
    # once in each. Merging them into one number would describe neither.
    fri = datetime(2026, 7, 17, 16, 0, tzinfo=timezone.utc)
    wed = datetime(2026, 7, 15, 14, 0, tzinfo=timezone.utc)  # 10:00 EDT
    week = _build(
        due_items=[_due(fri, "apply", est=60)],
        blocks=[ScheduledBlock(action_id="a1", title="Apply · HRT", at=wed, type="apply", est_minutes=60)],
    )
    friday = next(d for d in week["days"] if d["date"] == "2026-07-17")
    wednesday = next(d for d in week["days"] if d["date"] == "2026-07-15")
    assert (friday["due_est_minutes"], friday["scheduled_est_minutes"]) == (60, 0)
    assert (wednesday["due_est_minutes"], wednesday["scheduled_est_minutes"]) == (0, 60)


def test_blocks_land_on_the_local_day_and_arrive_sorted():
    # 2026-07-16 01:00 UTC is still 21:00 on the 15th in New York — the same
    # boundary rule the interviews follow.
    late = datetime(2026, 7, 16, 1, 0, tzinfo=timezone.utc)
    morning = datetime(2026, 7, 15, 14, 0, tzinfo=timezone.utc)
    week = _build(blocks=[
        ScheduledBlock(action_id="b", title="late", at=late, type="prep"),
        ScheduledBlock(action_id="a", title="morning", at=morning, type="prep"),
    ])
    day = next(d for d in week["days"] if d["date"] == "2026-07-15")
    assert [b["title"] for b in day["blocks"]] == ["morning", "late"]


def test_scheduled_minutes_also_use_the_per_type_default():
    # The mirror of the due-side test. Without this assertion, replacing
    # effective_est_minutes with a bare `or 0` on the scheduled side passes the
    # whole suite — a day drawn empty while its own blocks are visible in it.
    week = _build(blocks=[
        ScheduledBlock(action_id="a", title="no est", at=datetime(2026, 7, 15, 14, 0, tzinfo=timezone.utc), type="prep"),
        ScheduledBlock(action_id="b", title="also none", at=datetime(2026, 7, 15, 15, 0, tzinfo=timezone.utc), type="prep"),
    ])
    day = next(d for d in week["days"] if d["date"] == "2026-07-15")
    assert day["scheduled_est_minutes"] == 60  # prep defaults to 30 each, not 0


def test_a_finished_block_is_reported_as_finished():
    # due_* is pending-only while scheduled_* keeps completed work, so a cleared
    # day reads "0 owed, 1h placed". The renderer can only explain that if it
    # can see which blocks are done.
    week = _build(blocks=[
        ScheduledBlock(action_id="a", title="done one", at=datetime(2026, 7, 15, 14, 0, tzinfo=timezone.utc),
                       type="apply", est_minutes=60, status="done"),
    ])
    day = next(d for d in week["days"] if d["date"] == "2026-07-15")
    assert day["blocks"][0]["status"] == "done"
    assert day["scheduled_est_minutes"] == 60  # still counted: it is how the day went


def test_blocks_carry_a_resolved_estimate_so_the_strip_needs_no_table():
    week = _build(blocks=[
        ScheduledBlock(action_id="a", title="no est", at=datetime(2026, 7, 15, 14, 0, tzinfo=timezone.utc), type="apply"),
    ])
    day = next(d for d in week["days"] if d["date"] == "2026-07-15")
    assert day["blocks"][0]["est_minutes"] == 5  # the apply default, not None


def test_a_block_outside_the_week_is_ignored_not_clamped():
    outside = datetime(2026, 7, 25, 14, 0, tzinfo=timezone.utc)
    week = _build(blocks=[ScheduledBlock(action_id="a", title="next week", at=outside, type="apply")])
    assert all(d["blocks"] == [] for d in week["days"])
    assert all(d["scheduled_est_minutes"] == 0 for d in week["days"])

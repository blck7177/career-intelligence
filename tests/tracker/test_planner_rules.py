"""Unit tests for the pure planner rules engine (W2-C1). No DB — builds
ApplicationView/EventView/ActionView directly."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from packages.contracts.api.applications import (
    PUBLIC_PAYLOAD_KEYS,
    WEEKDAYS,
    PlannerSettings,
)
from packages.domain.planner.rules import (
    ActionView,
    ApplicationView,
    EventView,
    generate_actions,
    is_rest_day,
    local_day_start_utc,
    local_today,
    next_working_day,
)

NOW = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)  # 08:00 EDT, local date 2026-07-15


def _d(days_ago: int) -> datetime:
    return NOW - timedelta(days=days_ago)


def _app(**over) -> ApplicationView:
    base = dict(
        id="a1", status="applied", applied_at=_d(8), created_at=_d(8),
        events=[], actions=[],
    )
    base.update(over)
    return ApplicationView(**base)


def _gen(apps, *, settings=None, now=NOW, global_actions=None):
    return generate_actions(
        applications=apps,
        settings=settings or PlannerSettings(),
        now_utc=now,
        global_actions=global_actions,
    )


def _types(specs):
    return sorted(s.type for s in specs)


def _all_rules_firing():
    """One snapshot that trips every rule at once, so a change to any of them
    shows up in the whole-contract tests below."""
    return [
        _app(id="fu", applied_at=_d(8)),  # follow_up
        _app(id="ty", status="interviewing",
             events=[EventView("interview_scheduled", _d(0), at=NOW - timedelta(hours=2))]),
        _app(id="ci", status="interviewing",
             events=[EventView("interview_scheduled", _d(8), at=_d(8))]),  # check_in -> prep
        _app(id="ad", status="planned", applied_at=None, created_at=_d(15)),  # apply_or_drop
    ]  # queue_refill fires too: 1 planned < weekly target 10


def test_every_recorded_fact_is_exposed_by_the_api():
    """The whitelist and the engine must not drift. A fact the engine bothers to
    record but the API silently filters out is invisible for no reason the user
    could ever discover — this is the only thing that fails when a rule gains a
    field and nobody adds it to PUBLIC_PAYLOAD_KEYS."""
    specs = _gen(_all_rules_firing())
    assert {s.payload["rule"] for s in specs} == {
        "follow_up", "thank_you", "check_in", "apply_or_drop", "queue_refill",
    }, "fixture stopped tripping every rule — fix it, the coverage below depends on it"
    for s in specs:
        for key in s.payload:
            assert key in PUBLIC_PAYLOAD_KEYS, (
                f"rule {s.payload['rule']} records {key!r}, which the API filters out"
            )


def test_no_unused_keys_in_the_whitelist():
    """The reverse drift: a key nobody emits any more is a permission left open
    for something the engine no longer intends to say."""
    emitted = {k for s in _gen(_all_rules_firing()) for k in s.payload}
    assert PUBLIC_PAYLOAD_KEYS == emitted, (
        f"whitelist-only: {PUBLIC_PAYLOAD_KEYS - emitted}; emitted-only: {emitted - PUBLIC_PAYLOAD_KEYS}"
    )


# --- follow_up ---------------------------------------------------------------


def test_follow_up_fires_after_threshold():
    # created_at deliberately differs from applied_at: the reason line is about
    # how long ago you APPLIED, not how long the row has existed, and equal
    # fixtures would let the wrong one pass.
    specs = _gen([_app(applied_at=_d(8), created_at=_d(20))])
    fu = [s for s in specs if s.type == "follow_up"]
    assert len(fu) == 1
    assert fu[0].application_id == "a1"
    # due = local midnight (2026-07-15 00:00 EDT = 04:00 UTC)
    assert fu[0].due_at == local_day_start_utc(date(2026, 7, 15), "America/New_York")
    assert fu[0].est_minutes == 15
    # The row has to be able to explain itself: "applied 8 days ago, no reply".
    assert fu[0].payload == {"rule": "follow_up", "days_since_applied": 8}


def test_follow_up_no_fire_before_threshold():
    assert [s for s in _gen([_app(applied_at=_d(3))]) if s.type == "follow_up"] == []


def test_follow_up_suppressed_by_employer_response():
    app = _app(applied_at=_d(8), events=[EventView("interview_scheduled", _d(2))])
    assert [s for s in _gen([app]) if s.type == "follow_up"] == []


def test_follow_up_NOT_suppressed_by_user_note():
    # THE fix: a user's own note (or status_changed) must not cancel the reminder.
    app = _app(applied_at=_d(8), events=[EventView("note", _d(1)), EventView("status_changed", _d(8))])
    assert len([s for s in _gen([app]) if s.type == "follow_up"]) == 1


def test_follow_up_idempotent_when_pending_exists():
    app = _app(applied_at=_d(8), actions=[ActionView(type="follow_up", status="pending")])
    assert [s for s in _gen([app]) if s.type == "follow_up"] == []


def test_follow_up_suppressed_when_dismissed():
    # dismiss-resurrection fix: a dismissed auto follow_up stays dead.
    app = _app(applied_at=_d(8), actions=[ActionView(type="follow_up", status="dismissed")])
    assert [s for s in _gen([app]) if s.type == "follow_up"] == []


def test_follow_up_once_per_lifetime_after_completion():
    app = _app(applied_at=_d(30), actions=[ActionView(type="follow_up", status="done", completed_at=_d(20))])
    assert [s for s in _gen([app]) if s.type == "follow_up"] == []


def test_follow_up_no_fire_when_not_applied_status():
    assert [s for s in _gen([_app(status="planned", applied_at=None)]) if s.type == "follow_up"] == []


# --- apply_or_drop -----------------------------------------------------------


def test_apply_or_drop_fires():
    app = _app(status="planned", applied_at=None, created_at=_d(15))
    specs = [s for s in _gen([app]) if s.type == "apply"]
    assert len(specs) == 1
    assert specs[0].est_minutes == 60
    assert specs[0].payload == {"rule": "apply_or_drop", "days_planned": 15}


def test_apply_or_drop_no_fire_before_threshold():
    app = _app(status="planned", applied_at=None, created_at=_d(5))
    assert [s for s in _gen([app]) if s.type == "apply"] == []


def test_apply_or_drop_idempotent():
    app = _app(status="planned", applied_at=None, created_at=_d(15),
               actions=[ActionView(type="apply", status="pending")])
    assert [s for s in _gen([app]) if s.type == "apply"] == []


# --- queue_refill (global) ---------------------------------------------------


def test_queue_refill_fires_when_below_target():
    # Deliberately mixed: 2 planned among 3 applications, so planned_count can
    # not be satisfied by "however many applications there are".
    apps = [_app(id=f"p{i}", status="planned", applied_at=None, created_at=_d(1)) for i in range(2)]
    apps.append(_app(id="already-applied", status="applied", applied_at=_d(2)))
    globals_ = [s for s in _gen(apps) if s.type == "global"]
    assert len(globals_) == 1
    assert globals_[0].application_id is None
    assert globals_[0].est_minutes == 15
    # Carries both sides of the comparison it fired on, so the row can say
    # "2 queued against a target of 10".
    assert globals_[0].payload == {
        "rule": "queue_refill",
        "planned_count": 2,
        "target": 10,
    }


def test_queue_refill_no_fire_when_at_target():
    apps = [_app(id=f"p{i}", status="planned", applied_at=None, created_at=_d(1)) for i in range(10)]
    assert [s for s in _gen(apps) if s.type == "global"] == []


def test_queue_refill_deduped_within_week():
    apps = [_app(id="p1", status="planned", applied_at=None, created_at=_d(1))]
    existing = [ActionView(type="global", status="pending", created_at=_d(1), payload={"rule": "queue_refill"})]
    assert [s for s in _gen(apps, global_actions=existing) if s.type == "global"] == []


def test_queue_refill_dismissed_still_suppresses_this_week():
    apps = [_app(id="p1", status="planned", applied_at=None, created_at=_d(1))]
    existing = [ActionView(type="global", status="dismissed", created_at=_d(0), payload={"rule": "queue_refill"})]
    assert [s for s in _gen(apps, global_actions=existing) if s.type == "global"] == []


# --- thank_you / check_in (interview-driven; inert until W3 creates events) ---


def test_thank_you_fires_after_recent_interview():
    app = _app(status="interviewing", events=[EventView("interview_scheduled", _d(0), at=NOW - timedelta(hours=2))])
    ty = [s for s in _gen([app]) if s.type == "thank_you"]
    assert len(ty) == 1
    # due = day after the interview
    assert ty[0].due_at == local_day_start_utc(date(2026, 7, 16), "America/New_York")
    assert ty[0].est_minutes == 15
    assert ty[0].payload["rule"] == "thank_you"
    # The interview instant travels with the row so the UI can date the note.
    assert ty[0].payload["interview_at"] == (NOW - timedelta(hours=2)).isoformat()


def test_thank_you_no_fire_for_old_interview():
    app = _app(status="interviewing", events=[EventView("interview_scheduled", _d(3), at=_d(3))])
    assert [s for s in _gen([app]) if s.type == "thank_you"] == []


def test_check_in_fires_when_stale_after_interview():
    app = _app(status="interviewing", events=[EventView("interview_scheduled", _d(8), at=_d(8))])
    prep = [s for s in _gen([app]) if s.type == "prep"]
    assert len(prep) == 1
    assert prep[0].est_minutes == 30
    assert prep[0].payload == {"rule": "check_in", "days_since_interview": 8}


def test_check_in_no_fire_when_later_event_exists():
    app = _app(status="interviewing", events=[
        EventView("interview_scheduled", _d(8), at=_d(8)),
        EventView("note", _d(1)),
    ])
    assert [s for s in _gen([app]) if s.type == "prep"] == []


# --- timezone / due_at encoding ----------------------------------------------


def test_due_at_is_local_midnight_utc():
    # America/New_York in July is EDT (UTC-4): local 00:00 → 04:00 UTC.
    due = local_day_start_utc(date(2026, 7, 15), "America/New_York")
    assert due == datetime(2026, 7, 15, 4, 0, tzinfo=timezone.utc)


def test_fixture_clock_is_a_weekday():
    """Every "fires" test in this file depends on it: the default rest_days are
    sat+sun, so a NOW that drifted onto a weekend would silence the whole engine
    and the failures would point everywhere except here."""
    assert WEEKDAYS[local_today(NOW, "America/New_York").weekday()] == "wed"


def test_timezone_setting_shifts_today():
    # At 2026-07-15 02:00 UTC it is still 2026-07-14 in New York → applied 7 local
    # days earlier lands differently than a naive UTC diff. Verify tz is honored.
    now = datetime(2026, 7, 15, 2, 0, tzinfo=timezone.utc)  # 22:00 EDT on 07-14
    app = _app(applied_at=datetime(2026, 7, 7, 12, 0, tzinfo=timezone.utc))  # local 07-07
    fu = [s for s in _gen([app], now=now) if s.type == "follow_up"]
    # local today = 07-14; 07-14 - 07-07 = 7 days ≥ 7 → fires, due = 07-14 local midnight
    assert len(fu) == 1
    assert fu[0].due_at == local_day_start_utc(date(2026, 7, 14), "America/New_York")


# --- rest days (V5-C1) -------------------------------------------------------


def test_weekday_keys_are_indexed_by_python_weekday():
    """rules.py and week.py both index this tuple with date.weekday(); the
    contract validators only test membership. Reordering it would therefore keep
    every validator green while shifting every rest day and every strip stripe by
    a day, so pin the mapping to real dates."""
    assert len(WEEKDAYS) == 7
    assert WEEKDAYS[date(2026, 7, 13).weekday()] == "mon"  # a known Monday
    assert WEEKDAYS[date(2026, 7, 18).weekday()] == "sat"


def test_rest_day_suppresses_every_rule_except_the_perishable_one():
    """Asserted against the snapshot that trips EVERY rule, so a guard wired into
    only some of them still fails here. thank_you is the deliberate exemption:
    its trigger is a 24h window, so suppressing it destroys the reminder instead
    of deferring it (see test_thank_you_survives_the_weekend)."""
    apps = _all_rules_firing()
    assert set(_types(_gen(apps))) == {"apply", "follow_up", "global", "prep", "thank_you"}
    assert _types(_gen(apps, settings=PlannerSettings(rest_days=["wed"]))) == ["thank_you"]


def test_default_rest_days_silence_the_weekend():
    """The product default is ["sat", "sun"], so the beat goes quiet on the
    weekend with nothing configured. Both clocks are built off the Saturday so the
    application is equally ripe on each — the only difference is the weekday."""
    sat = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)  # 08:00 EDT, Saturday
    app = _app(applied_at=sat - timedelta(days=8))
    assert _gen([app], now=sat - timedelta(days=1)) != []  # Friday: fires
    assert _gen([app], now=sat) == []  # Saturday: silent


def test_rest_day_is_resolved_in_the_workspace_timezone():
    """The same instant is Friday night in New York and Saturday lunchtime in
    Tokyo. A UTC-based check would silence Friday evening for the New Yorker —
    exactly the hour someone squeezes in a follow-up before the weekend."""
    instant = datetime(2026, 7, 18, 3, 0, tzinfo=timezone.utc)  # 23:00 EDT Fri / 12:00 JST Sat
    ny = PlannerSettings(rest_days=["sat"])
    tokyo = PlannerSettings(timezone="Asia/Tokyo", rest_days=["sat"])

    assert is_rest_day(ny, instant) is False
    assert is_rest_day(tokyo, instant) is True

    app = _app(applied_at=datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc))
    assert _gen([app], settings=ny, now=instant) != []
    assert _gen([app], settings=tokyo, now=instant) == []


def test_rest_days_empty_means_never_rest():
    """rest_days is user-editable down to an empty list; that must read as "no day
    off", not as a falsy value some guard treats as "today"."""
    apps = _all_rules_firing()
    assert len(_gen(apps, settings=PlannerSettings(rest_days=[]))) == 5


# --- the perishable rule: thank_you must survive a rest day -------------------


def test_thank_you_survives_the_weekend():
    """THE regression this exemption exists for. Interview Friday 16:00 EDT; the
    beat fires daily at 10:00 UTC. Saturday's run is the only one inside the 24h
    window, and with the default sat+sun rest days a plain skip means the
    thank-you note is never suggested at all — silently, for the most
    time-critical prompt in the planner."""
    interview = datetime(2026, 7, 17, 20, 0, tzinfo=timezone.utc)  # Fri 16:00 EDT
    app = _app(id="ty", status="interviewing", applied_at=_d(20), created_at=_d(20),
               events=[EventView("interview_scheduled", interview, at=interview)])
    saturday_beat = datetime(2026, 7, 18, 10, 0, tzinfo=timezone.utc)  # 06:00 EDT

    specs = _gen([app], now=saturday_beat)  # default rest_days = sat, sun
    assert _types(specs) == ["thank_you"]  # and nothing else: no new debt
    # Due Monday, not Saturday: the reminder is kept, the day off stays off.
    assert specs[0].due_at == local_day_start_utc(date(2026, 7, 20), "America/New_York")


def test_thank_you_due_date_skips_rest_days_even_on_a_working_day():
    """The only rule that dates a FUTURE day is the only one that can schedule
    work onto a day the user marked off. Interview Wednesday with Thursday as the
    rest day → due Friday."""
    interview = NOW - timedelta(hours=2)  # Wednesday
    app = _app(id="ty", status="interviewing",
               events=[EventView("interview_scheduled", interview, at=interview)])
    specs = _gen([app], settings=PlannerSettings(rest_days=["thu"]))
    ty = [s for s in specs if s.type == "thank_you"]
    assert len(ty) == 1
    assert ty[0].due_at == local_day_start_utc(date(2026, 7, 17), "America/New_York")  # Fri


def test_next_working_day_terminates_when_every_day_is_a_rest_day():
    """rest_days can legitimately hold all seven. A "find the next workday" loop
    over that would never end; falling back to the day itself keeps the to-do
    visible instead of deleting it."""
    all_off = PlannerSettings(rest_days=list(WEEKDAYS))
    assert next_working_day(all_off, date(2026, 7, 18)) == date(2026, 7, 18)
    # And the normal case is unchanged: a working day is its own next working day.
    assert next_working_day(PlannerSettings(), date(2026, 7, 15)) == date(2026, 7, 15)

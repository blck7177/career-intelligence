"""Unit tests for the pure funnel/alerts builder (W3-C2)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from packages.contracts.api.applications import PlannerSettings
from packages.domain.planner.funnel import build_funnel
from packages.domain.planner.rules import ApplicationView, EventView

NOW = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)


def _d(days: int) -> datetime:
    return NOW - timedelta(days=days)


def _app(id, status, *, applied_days=None, events=None) -> ApplicationView:
    return ApplicationView(
        id=id,
        status=status,
        applied_at=_d(applied_days) if applied_days is not None else None,
        created_at=_d(applied_days if applied_days is not None else 1),
        events=events or [],
        actions=[],
    )


def _f(apps, settings=None):
    return build_funnel(apps, settings or PlannerSettings(), NOW)


def _stages(r):
    return {s["key"]: s["count"] for s in r["stages"]}


def _kinds(r):
    return [a["kind"] for a in r["alerts"]]


def test_stage_counts():
    apps = [
        _app("1", "planned"),
        _app("2", "applied", applied_days=1),
        _app("3", "interviewing", applied_days=5),
        _app("4", "offer", applied_days=10),
    ]
    s = _stages(_f(apps))
    assert s["planned"] == 1 and s["applied"] == 1 and s["interviewing"] == 1 and s["offer"] == 1
    assert s["onsite"] == 0


def test_onsite_derived_from_interview_event():
    ev = EventView("interview_scheduled", _d(2), at=_d(2), round_type="onsite")
    s = _stages(_f([_app("1", "interviewing", applied_days=5, events=[ev])]))
    assert s["onsite"] == 1


def test_onsite_not_counted_when_closed():
    ev = EventView("interview_scheduled", _d(2), at=_d(2), round_type="onsite")
    s = _stages(_f([_app("1", "rejected", applied_days=5, events=[ev])]))
    assert s["onsite"] == 0


def test_ghosted_suggestion_alert():
    r = _f([_app("1", "applied", applied_days=20)])  # ≥ ghost_days(14), no event
    assert "ghosted_suggestion" in _kinds(r)
    g = next(a for a in r["alerts"] if a["kind"] == "ghosted_suggestion")
    assert g["application_id"] == "1" and g["context"]["days"] == 20


def test_ghosted_suggestion_suppressed_by_interview():
    ev = EventView("interview_scheduled", _d(1), at=_d(1), round_type="phone")
    r = _f([_app("1", "applied", applied_days=20, events=[ev])])
    assert "ghosted_suggestion" not in _kinds(r)


def test_check_in_alert_when_stale_interviewing():
    ev = EventView("interview_scheduled", _d(10), at=_d(10), round_type="phone")
    assert "check_in" in _kinds(_f([_app("1", "interviewing", applied_days=15, events=[ev])]))


def test_onsite_low_alert():
    assert "onsite_low" in _kinds(_f([_app("1", "applied", applied_days=1)]))


def test_supply_drought_needs_late_stage():
    # a late-stage app in play but ~0 applies this week → drought
    assert "supply_drought" in _kinds(_f([_app("1", "interviewing", applied_days=20)]))
    # no late-stage → no drought even at 0 applies
    assert "supply_drought" not in _kinds(_f([_app("1", "planned")]))

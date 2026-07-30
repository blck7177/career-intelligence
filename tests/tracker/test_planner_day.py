"""V6-C1 — the day log: morning commitment, evening close, and the arithmetic
that has to agree with what the user was shown."""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from packages.contracts.api.applications import ActionType
from packages.domain.planner.rules import DEFAULT_EST_MINUTES, effective_est_minutes
from packages.infrastructure.db.repositories import (
    ApplicationActionRepository,
    JobApplicationRepository,
    PlannerDayLogRepository,
    WorkspaceRepository,
)

DAY = date(2026, 7, 15)  # a Wednesday
NOW = datetime(2026, 7, 15, 21, 0, tzinfo=timezone.utc)


def _utc(dt):
    """SQLite drops tzinfo on round-trip; postgres keeps it."""
    return dt if dt is None or dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _ws(db, ws_id: str):
    WorkspaceRepository(db).create(name=ws_id, workspace_id=ws_id)
    return JobApplicationRepository(db).create(
        workspace_id=ws_id, job_id="j1", status="applied"
    )


# --- the estimate table both sides do arithmetic with -----------------------


def test_every_action_type_has_an_estimate():
    """effective_est_minutes has to answer for EVERY type, because it totals a
    day. A type missing from the table falls to a bare literal, and a to-do
    quietly worth 20 minutes in one place and 15 in another makes the weekly
    plan-versus-actual compare two different accountings."""
    from typing import get_args

    missing = [t for t in get_args(ActionType) if t not in DEFAULT_EST_MINUTES]
    assert missing == [], f"no default estimate for {missing}"


def test_frontend_and_backend_estimate_tables_agree():
    """The Today view keeps its own copy (it renders before any of this runs).
    The number the user sees in the capacity bar becomes the number stored as
    their commitment, so the two tables have to hold the same values — and
    nothing but this test connects them across the language boundary."""
    src = (
        Path(__file__).resolve().parents[2]
        / "apps/web/src/app/[locale]/tracker/PlanToday.tsx"
    ).read_text()
    block = re.search(r"EST_FALLBACK[^=]*=\s*\{(.*?)\}", src, re.S)
    assert block, "EST_FALLBACK not found in PlanToday.tsx — did it move?"
    frontend = {
        m.group(1): int(m.group(2))
        for m in re.finditer(r"(\w+)\s*:\s*(\d+)", block.group(1))
    }
    assert frontend == DEFAULT_EST_MINUTES, (
        f"estimate tables drifted.\n  frontend-only: "
        f"{set(frontend.items()) - set(DEFAULT_EST_MINUTES.items())}\n"
        f"  backend-only: {set(DEFAULT_EST_MINUTES.items()) - set(frontend.items())}"
    )


def test_effective_estimate_falls_back_only_when_unset():
    assert effective_est_minutes("apply", 45) == 45  # explicit wins
    assert effective_est_minutes("apply", None) == 60  # per-type default
    assert effective_est_minutes("apply", 0) == 0  # 0 is a value, not "unset"
    assert effective_est_minutes("something_new", None) == 20  # unknown type


# --- committed_est ----------------------------------------------------------


def test_commit_sums_effective_estimates_including_unestimated_rows(db_session):
    """An unestimated to-do still costs the user time. Summing raw columns and
    treating NULL as zero would file a lighter morning than the one they saw."""
    app = _ws(db_session, "ws1")
    repo = ApplicationActionRepository(db_session)
    a = repo.create(workspace_id="ws1", type="apply", title="a", application_id=app.id, est_minutes=45)
    b = repo.create(workspace_id="ws1", type="prep", title="b", application_id=app.id)  # NULL -> 30
    db_session.flush()

    total = repo.sum_est_for_ids("ws1", [a.id, b.id])
    assert total == 75, "45 explicit + 30 from the prep default"


def test_commit_ignores_ids_from_another_workspace(db_session):
    """Workspace scoping, and the reason it is silent: the kept list is a
    snapshot of a UI that may have moved. A foreign id contributes nothing."""
    mine = _ws(db_session, "ws2")
    theirs = _ws(db_session, "ws3")
    repo = ApplicationActionRepository(db_session)
    a = repo.create(workspace_id="ws2", type="apply", title="mine", application_id=mine.id, est_minutes=60)
    b = repo.create(workspace_id="ws3", type="apply", title="theirs", application_id=theirs.id, est_minutes=60)
    db_session.flush()

    assert repo.sum_est_for_ids("ws2", [a.id, b.id]) == 60
    assert repo.sum_est_for_ids("ws2", ["no-such-id"]) == 0
    assert repo.sum_est_for_ids("ws2", []) == 0


def test_recommitting_replaces_the_snapshot(db_session):
    """Re-running the ritual means the user changed their mind; the evening
    comparison must measure the plan they are actually working against."""
    _ws(db_session, "ws4")
    repo = PlannerDayLogRepository(db_session)
    repo.commit_day("ws4", DAY, committed_est=90)
    repo.commit_day("ws4", DAY, committed_est=45)
    assert repo.get_for_date("ws4", DAY).committed_est == 45


# --- done_est / close -------------------------------------------------------


def test_done_est_counts_only_this_day_and_only_completed(db_session):
    """The window is the local day. Work finished yesterday, work finished
    tomorrow, and work still pending all stay out of today's number."""
    app = _ws(db_session, "ws5")
    repo = ApplicationActionRepository(db_session)
    start = datetime(2026, 7, 15, 4, 0, tzinfo=timezone.utc)  # 00:00 EDT
    end = start + timedelta(days=1)

    done_today = repo.create(workspace_id="ws5", type="apply", title="in", application_id=app.id, est_minutes=60)
    done_today.status = "done"
    done_today.completed_at = start + timedelta(hours=10)
    done_yesterday = repo.create(workspace_id="ws5", type="apply", title="before", application_id=app.id, est_minutes=60)
    done_yesterday.status = "done"
    done_yesterday.completed_at = start - timedelta(hours=1)
    still_pending = repo.create(workspace_id="ws5", type="apply", title="open", application_id=app.id, est_minutes=60)
    unestimated = repo.create(workspace_id="ws5", type="prep", title="no est", application_id=app.id)
    unestimated.status = "done"
    unestimated.completed_at = start + timedelta(hours=11)
    db_session.flush()
    assert still_pending.status == "pending"

    assert repo.sum_est_completed_in_range("ws5", start, end) == 90  # 60 + prep's 30


def test_close_keeps_the_first_closed_at_but_refreshes_done_est(db_session):
    """Reopening the laptop after closing changes what was done; it does not
    change when you declared the day over."""
    _ws(db_session, "ws6")
    repo = PlannerDayLogRepository(db_session)
    first = repo.close_day("ws6", DAY, done_est=30, reflection="ok", now_utc=NOW)
    assert _utc(first.closed_at) == NOW

    again = repo.close_day(
        "ws6", DAY, done_est=75, reflection=None, now_utc=NOW + timedelta(hours=2)
    )
    assert _utc(again.closed_at) == NOW, "closed_at moved"
    assert again.done_est == 75, "done_est did not refresh"
    assert again.reflection == "ok", "a blank reflection erased the written one"


def test_closing_a_day_that_was_never_planned(db_session):
    """A real thing to do. committed_est stays NULL — which is the truth, and
    better than inventing a commitment for the comparison to measure against."""
    _ws(db_session, "ws7")
    repo = PlannerDayLogRepository(db_session)
    row = repo.close_day("ws7", DAY, done_est=40, reflection=None, now_utc=NOW)
    assert row.committed_est is None
    assert row.done_est == 40


def test_commit_then_close_share_one_row(db_session):
    """The unique (workspace, local_date) is what makes the day a single record
    rather than two half-records the weekly view has to reconcile."""
    _ws(db_session, "ws8")
    repo = PlannerDayLogRepository(db_session)
    repo.commit_day("ws8", DAY, committed_est=90)
    repo.close_day("ws8", DAY, done_est=60, reflection="slow start", now_utc=NOW)

    rows = repo.list_for_range("ws8", DAY, DAY + timedelta(days=1))
    assert len(rows) == 1
    assert (rows[0].committed_est, rows[0].done_est, rows[0].reflection) == (90, 60, "slow start")


def test_list_for_range_is_half_open_and_ordered(db_session):
    """The weekly review zips this against a Mon..Sun week, so the end day must
    be excluded and the order must be the calendar's."""
    _ws(db_session, "ws9")
    repo = PlannerDayLogRepository(db_session)
    for offset in (2, 0, 1, 7):  # deliberately out of order, 7 is outside
        repo.commit_day("ws9", DAY + timedelta(days=offset), committed_est=offset)

    rows = repo.list_for_range("ws9", DAY, DAY + timedelta(days=7))
    assert [r.local_date for r in rows] == [DAY, DAY + timedelta(days=1), DAY + timedelta(days=2)]


def test_day_logs_are_workspace_scoped(db_session):
    _ws(db_session, "ws10")
    _ws(db_session, "ws11")
    repo = PlannerDayLogRepository(db_session)
    repo.commit_day("ws10", DAY, committed_est=90)
    assert repo.get_for_date("ws11", DAY) is None
    assert repo.list_for_range("ws11", DAY, DAY + timedelta(days=1)) == []

"""Pure unit tests for the application status machine."""
from __future__ import annotations

import pytest

from packages.domain.applications.transitions import (
    ALLOWED_TRANSITIONS,
    STATUS_GROUPS,
    InvalidTransition,
    assert_transition,
    is_allowed,
)


def test_forward_skips_allowed():
    assert is_allowed("planned", "applied")
    assert is_allowed("applied", "interviewing")  # skip in_review
    assert is_allowed("planned", "offer")  # big skip, still forward


def test_any_live_state_can_close():
    for live in ("planned", "applied", "in_review", "interviewing", "offer"):
        assert is_allowed(live, "rejected")
        assert is_allowed(live, "withdrawn")
        assert is_allowed(live, "ghosted")


def test_backward_rejected_without_force():
    with pytest.raises(InvalidTransition):
        assert_transition("interviewing", "applied")


def test_backward_allowed_with_force():
    assert_transition("interviewing", "applied", force=True)  # no raise


def test_terminal_states_are_stuck_without_force():
    with pytest.raises(InvalidTransition):
        assert_transition("rejected", "applied")
    assert_transition("rejected", "applied", force=True)  # force reopens


def test_same_status_rejected():
    with pytest.raises(InvalidTransition):
        assert_transition("applied", "applied")


def test_unknown_status_rejected_even_with_force():
    with pytest.raises(InvalidTransition):
        assert_transition("applied", "bogus", force=True)


def test_status_groups_partition_all_statuses():
    grouped = set().union(*STATUS_GROUPS.values())
    assert grouped == set(ALLOWED_TRANSITIONS.keys())

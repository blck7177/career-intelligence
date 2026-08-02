"""Application status machine — pure functions, no DB.

Single source of truth for legal status transitions and status groupings,
shared by the repository layer (JobApplicationRepository.transition_status)
and the API layer (Commit 2). Kept dependency-free so it is trivially
unit-testable.

Funnel:
    planned -> applied -> in_review -> interviewing -> offer
                                                   \\-> rejected | withdrawn | ghosted

Design choices (see dev_note/career/tracker/planner_tracker_design_0724.md):
  - Forward *skips* are legal — an application often jumps applied ->
    interviewing without an observed in_review step.
  - Any live state can close out (rejected/withdrawn/ghosted).
  - Backward moves and reopening a closed application are "I mis-recorded"
    corrections; they require force=True and are recorded as events.
  - Interview *rounds* are application_events, not statuses.
"""

from __future__ import annotations

STATUSES: tuple[str, ...] = (
    "planned",
    "applied",
    "in_review",
    "interviewing",
    "offer",
    "rejected",
    "withdrawn",
    "ghosted",
)

# Terminal / closed states — an application stops moving forward here.
CLOSED_STATUSES = frozenset({"rejected", "withdrawn", "ghosted"})
# In-flight states shown under the "active" filter.
ACTIVE_STATUSES = frozenset({"applied", "in_review", "interviewing", "offer"})
PLANNED_STATUSES = frozenset({"planned"})

# The three groups the sidebar lists, and the `status_group` list filter behind
# them. Their union is every status.
STATUS_GROUPS: dict[str, frozenset[str]] = {
    "planned": PLANNED_STATUSES,
    "active": ACTIVE_STATUSES,
    "closed": CLOSED_STATUSES,
}

# Forward moves along the main funnel (skips intentional).
_FORWARD: dict[str, set[str]] = {
    "planned": {"applied", "in_review", "interviewing", "offer"},
    "applied": {"in_review", "interviewing", "offer"},
    "in_review": {"interviewing", "offer"},
    "interviewing": {"offer"},
    "offer": set(),
}
# Any live state can be closed out. (offer -> withdrawn = declined an offer;
# offer -> rejected = offer rescinded.)
_CLOSEABLE_FROM = frozenset({"planned", "applied", "in_review", "interviewing", "offer"})

# current status -> allowed next states (excluding force overrides).
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    status: frozenset(
        _FORWARD.get(status, set()) | (CLOSED_STATUSES if status in _CLOSEABLE_FROM else set())
    )
    for status in STATUSES
}


class InvalidTransition(ValueError):
    """Raised when a status change is not allowed by the state machine."""


def is_allowed(current: str, new: str) -> bool:
    """True if ``current -> new`` is a legal forward/closing transition."""
    return new in ALLOWED_TRANSITIONS.get(current, frozenset())


def assert_transition(current: str, new: str, *, force: bool = False) -> None:
    """Raise :class:`InvalidTransition` unless ``current -> new`` is legal.

    ``force=True`` bypasses the funnel rules (correcting a mis-recorded status,
    e.g. a backward move, or reopening a closed application) but still rejects
    unknown status strings.
    """
    if new not in STATUSES:
        raise InvalidTransition(f"unknown status: {new!r}")
    if current not in STATUSES:
        raise InvalidTransition(f"unknown current status: {current!r}")
    if force:
        return
    if new == current:
        raise InvalidTransition(f"application is already {new!r}")
    if not is_allowed(current, new):
        raise InvalidTransition(f"illegal transition: {current!r} -> {new!r}")

"""ORM → planner domain-view mappers. Infra depends on domain (not vice-versa),
so the ORM→view mapping lives here once and is shared by the worker (rules) and
the funnel endpoint."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from packages.domain.planner.rules import ActionView, ApplicationView, EventView


def event_view(e: Any) -> EventView:
    payload = e.payload_json if isinstance(e.payload_json, dict) else None
    at = None
    round_type = None
    if payload:
        raw = payload.get("at")
        if raw:
            try:
                at = datetime.fromisoformat(raw)
            except (TypeError, ValueError):
                at = None
        round_type = payload.get("round_type")
    return EventView(event_type=e.event_type, created_at=e.created_at, at=at, round_type=round_type)


def action_view(a: Any) -> ActionView:
    return ActionView(
        type=a.type,
        status=a.status,
        auto_generated=a.auto_generated,
        completed_at=a.completed_at,
        created_at=a.created_at,
        payload=a.payload_json,
    )


def application_view(app: Any, events: list, actions: list) -> ApplicationView:
    return ApplicationView(
        id=app.id,
        status=app.status,
        applied_at=app.applied_at,
        created_at=app.created_at,
        events=[event_view(e) for e in events],
        actions=[action_view(a) for a in actions],
    )

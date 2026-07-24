"""Shared planner-settings loader — one merge, used by both the API route and the
worker so defaults never drift between read and rule-generation."""
from __future__ import annotations

from typing import Any

from packages.contracts.api.applications import PlannerSettings


def load_planner_settings(workspace: Any) -> PlannerSettings:
    """Merge the workspace's stored planner_settings_json over the product
    defaults. `workspace` is any object exposing `planner_settings_json`
    (the ORM Workspace); no DB access here."""
    stored = getattr(workspace, "planner_settings_json", None) or {}
    return PlannerSettings(**stored)

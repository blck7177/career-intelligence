"""Planner domain — pure functions for the tracker's planner/Today layer.

- settings.load_planner_settings: merge stored overrides over PlannerSettings defaults.
- rules.generate_actions: the daily rules engine (pure; the worker calls it and
  persists the returned specs).
"""

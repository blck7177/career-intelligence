"""Reflect task input payload — enriched by worker before agent invocation."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from packages.contracts.strategy.state import SearchStrategyState


class ReflectionTaskPayload(BaseModel):
    """
    Written to input.json payload for career-reflect-agent.

    The worker enriches RunReflectionInput with artifact paths and current strategy.
    """

    reflected_run_id: str
    max_tool_calls: int = Field(default=10, ge=1, le=100)
    timeout_seconds: int = Field(default=300, ge=60, le=3600)

    coverage_report_path: Optional[str] = None
    search_ledger_path: Optional[str] = None
    candidate_pool_path: Optional[str] = None
    reflected_run_summary: dict[str, Any] = Field(default_factory=dict)
    current_strategy_state: Optional[SearchStrategyState] = None

"""Cross-run search strategy contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

CoverageLevel = Literal["sufficient", "weak", "missing", "unknown"]


class StrategyPatch(BaseModel):
    """Proposed strategy changes from career-reflect-agent (flat object, all fields optional)."""

    effective_sources: list[str] = Field(default_factory=list)
    avoid_sources: list[str] = Field(default_factory=list)
    effective_query_patterns: list[str] = Field(default_factory=list)
    avoid_query_patterns: list[str] = Field(default_factory=list)
    coverage_by_role_category: dict[str, CoverageLevel] = Field(default_factory=dict)
    key_learnings: list[str] = Field(default_factory=list)
    recommended_next_searches: list[str] = Field(default_factory=list)


class SearchStrategyState(BaseModel):
    """Platform-owned canonical strategy state for a workspace."""

    workspace_id: str
    profile_id: Optional[str] = None

    effective_sources: list[str] = Field(default_factory=list)
    avoid_sources: list[str] = Field(default_factory=list)
    effective_query_patterns: list[str] = Field(default_factory=list)
    avoid_query_patterns: list[str] = Field(default_factory=list)
    coverage_by_role_category: dict[str, CoverageLevel] = Field(default_factory=dict)
    key_learnings: list[str] = Field(default_factory=list)
    recommended_next_searches: list[str] = Field(default_factory=list)

    last_reflection_run_id: Optional[str] = None
    last_reflection_task_id: Optional[str] = None
    updated_at: datetime

    @classmethod
    def empty(cls, workspace_id: str, *, profile_id: str | None = None) -> SearchStrategyState:
        from datetime import timezone

        return cls(
            workspace_id=workspace_id,
            profile_id=profile_id,
            updated_at=datetime.now(timezone.utc),
        )


class StrategyPatchError(Exception):
    """Raised when a strategy patch fails validation or apply."""

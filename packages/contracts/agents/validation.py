"""
Validator gate result contract.

Written to agent_validation_results table after every agent invocation,
regardless of pass/fail.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


class ValidationError(BaseModel):
    field: str
    message: str
    value: str | None = None


class ValidationWarning(BaseModel):
    field: str
    message: str


class AgentValidationResult(BaseModel):
    """
    Result of running the Validator Gate on an agent output manifest.
    Persisted to agent_validation_results table.
    """

    invocation_id: str
    validator_name: str
    status: Literal["passed", "failed", "warning"]
    errors: list[ValidationError] = Field(default_factory=list)
    warnings: list[ValidationWarning] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def passed(self) -> bool:
        return self.status in ("passed", "warning")

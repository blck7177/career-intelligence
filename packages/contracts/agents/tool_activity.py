"""
Gateway-observed tool activity contracts.

The runtime writes ToolActivitySummary to disk after each invocation.
ValidatorGate can then use this gateway-side record as a higher-trust
evidence source than agent-authored manifest fields.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ToolCallRecord(BaseModel):
    """One observed tool call during a single invocation."""

    tool: str
    timestamp: str | None = None
    status: str = "unknown"
    source: str = "gateway_session"
    output_artifact: str | None = None


class ToolActivitySummary(BaseModel):
    """Gateway-side activity summary for an invocation."""

    invocation_id: str
    session_key: str
    transport: str | None = None
    fallback_from: str | None = None
    session_file: str | None = None
    tool_call_count: int = 0
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    parse_errors: list[str] = Field(default_factory=list)

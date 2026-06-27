"""
LLM usage tracking — contextvar-based cost ledger for deterministic LLM calls.

Usage in worker task handlers:

    from packages.infrastructure.llm.usage_writer import set_llm_context

    def handle_some_task(env: TaskEnvelope) -> dict:
        set_llm_context(run_id=env.run_id, task_id=env.task_id,
                        workspace_id=env.workspace_id, call_site="job_report")
        ...  # any LLMClient calls within this context are automatically recorded

The LLMClient calls _emit_usage() after each API call, which reads the
contextvar and writes a row to llm_usage_events via a background-safe path.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LLMCallContext:
    run_id: str = ""
    task_id: str = ""
    workspace_id: str = ""
    call_site: str = "unknown"


_llm_context: ContextVar[LLMCallContext | None] = ContextVar(
    "_llm_context", default=None
)


def set_llm_context(
    *,
    run_id: str = "",
    task_id: str = "",
    workspace_id: str = "",
    call_site: str = "unknown",
) -> None:
    _llm_context.set(LLMCallContext(
        run_id=run_id,
        task_id=task_id,
        workspace_id=workspace_id,
        call_site=call_site,
    ))


def get_llm_context() -> LLMCallContext | None:
    return _llm_context.get()


# ---------------------------------------------------------------------------
# Pricing table (USD per 1M tokens)
# ---------------------------------------------------------------------------

_PRICING: dict[str, tuple[float, float]] = {
    # (prompt_per_1M, completion_per_1M)
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-nano": (0.10, 0.40),
    "gpt-5.4-mini": (0.15, 0.60),
    "o1": (15.00, 60.00),
    "o1-mini": (3.00, 12.00),
    "o3": (10.00, 40.00),
    "o3-mini": (1.10, 4.40),
    "o4-mini": (1.10, 4.40),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5": (0.80, 4.00),
    "claude-opus-4-8": (15.00, 75.00),
}


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float | None:
    for prefix, (prompt_rate, completion_rate) in _PRICING.items():
        if model.startswith(prefix):
            return (
                prompt_tokens * prompt_rate / 1_000_000
                + completion_tokens * completion_rate / 1_000_000
            )
    return None


# ---------------------------------------------------------------------------
# DB writer — called by LLMClient._emit_usage()
# ---------------------------------------------------------------------------


def persist_usage(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
) -> None:
    ctx = _llm_context.get()

    cost = estimate_cost(model, prompt_tokens, completion_tokens)

    try:
        from packages.infrastructure.db.session import get_session
        from packages.infrastructure.db.models import LLMUsageEvent

        with get_session() as session:
            event = LLMUsageEvent(
                run_id=ctx.run_id if ctx and ctx.run_id else None,
                task_id=ctx.task_id if ctx and ctx.task_id else None,
                workspace_id=ctx.workspace_id if ctx and ctx.workspace_id else None,
                call_site=ctx.call_site if ctx else "unknown",
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                estimated_cost_usd=cost,
            )
            session.add(event)
            session.commit()
    except Exception:
        logger.warning(
            "Failed to persist LLM usage event (non-blocking): "
            "model=%s tokens=%d/%d",
            model, prompt_tokens, completion_tokens,
            exc_info=True,
        )


# ---------------------------------------------------------------------------
# Agent (OpenClaw) usage — called by worker after agent invocation completes
# ---------------------------------------------------------------------------


def persist_agent_usage(
    *,
    run_id: str,
    task_id: str,
    workspace_id: str,
    call_site: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> None:
    """Write a single llm_usage_events row for an OpenClaw agent invocation."""
    total = input_tokens + output_tokens
    if total == 0:
        return

    cost = estimate_cost(model, input_tokens, output_tokens)

    try:
        from packages.infrastructure.db.session import get_session
        from packages.infrastructure.db.models import LLMUsageEvent

        with get_session() as session:
            event = LLMUsageEvent(
                run_id=run_id or None,
                task_id=task_id or None,
                workspace_id=workspace_id or None,
                call_site=call_site,
                model=model,
                prompt_tokens=input_tokens,
                completion_tokens=output_tokens,
                total_tokens=total,
                estimated_cost_usd=cost,
            )
            session.add(event)
            session.commit()
    except Exception:
        logger.warning(
            "Failed to persist agent usage event (non-blocking): "
            "model=%s tokens=%d/%d",
            model, input_tokens, output_tokens,
            exc_info=True,
        )

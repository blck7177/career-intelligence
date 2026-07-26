"""
OpenClawHttpRuntime — HTTP client implementation of AgentRuntime.

Architecture role
------------------
Alternative to OpenClawGatewayRuntime (openclaw.py). Instead of shelling out
to the `openclaw` CLI (which forks a ~500MB Node/V8 process per invocation —
see dev_note/career/phase20-launch-hardening/session_report_0711_full.md and
the independent prototype at ~/openclaw-http-rpc-prototype), this calls the
gateway's own `POST /v1/chat/completions` HTTP endpoint directly. The already-
running openclaw-gateway daemon handles the request in-process; no new
process is spawned per invocation. Verified in the prototype (4 rounds,
including real career-research-operator and career-search-operator skill
runs) at ~12-60MB marginal memory per concurrent invocation vs ~500MB/CLI
invocation, with no framework-imposed concurrency ceiling
(agents.defaults.maxConcurrent is a soft, queueing threshold).

What this does NOT need to reimplement (verified against career-intelligence's
own validator/ingestion code, not assumed):
  - agent_tool_events / anti-fabrication evidence: ToolLedgerValidator reads
    tool_events.jsonl (the HMAC-signed ledger the exec wrappers write)
    directly from the shared artifacts volume. That's written by the agent's
    own exec calls inside the gateway process, independent of how the
    invocation was triggered.
  - career_fetch_source's domain rate limiter: same reasoning — runs inside
    the gateway process regardless of transport.
  - GatewayTransportValidator: reads gateway_tool_activity.json "if present;
    passes silently if absent" (its own docstring). This runtime deliberately
    does not write that file — there is no CLI-embedded-fallback failure mode
    to detect when the invocation went straight to the gateway's own HTTP
    endpoint, so leaving it absent is correct, not a gap.

What this DOES need that the CLI path got for free from its rich --json
stdout: the underlying provider/model string for cost accounting. The
/v1/chat/completions response's top-level `model` field is the echoed
request target ("openclaw/<agent_id>"), not the real provider model — see
usage_writer.py's estimate_cost(), which prefix-matches against real model
names like "gpt-5.4-mini". This reads agents.defaults.model.primary from the
same OPENCLAW_CONFIG_PATH file already mounted for the CLI path. That's a
real assumption (one global default model, no per-agent override) that holds
today but would need revisiting if per-agent models are introduced.

Usage
-----
Use create_http_runtime() as the construction point, mirroring create_runtime()
in openclaw.py.
"""

from __future__ import annotations

import json
import logging
import os
import time

import httpx

from packages.contracts.agents.invocation import (
    AgentInvocationResult,
    AgentInvocationSpec,
    AgentUsageSummary,
)
from packages.infrastructure.agent_runtime.base import AgentRuntime
from packages.infrastructure.agent_runtime.message import build_invocation_message

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = os.environ.get("OPENCLAW_GATEWAY_HTTP_URL", "http://127.0.0.1:18789")
_DEFAULT_CONFIG_PATH = os.environ.get("OPENCLAW_CONFIG_PATH")


class OpenClawHttpRuntime(AgentRuntime):
    """
    Invokes OpenClaw agents via the gateway's POST /v1/chat/completions
    endpoint instead of the `openclaw agent` CLI.

    Requires gateway.http.endpoints.chatCompletions.enabled: true in the
    gateway's config (off by default) and a reachable gateway.auth.token.
    """

    def __init__(
        self,
        base_url: str = _DEFAULT_BASE_URL,
        config_path: str | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._config_path = config_path or _DEFAULT_CONFIG_PATH
        self._connect_timeout = timeout_seconds
        self._token: str | None = None
        self._model: str = ""

    def _load_gateway_config(self) -> None:
        """Read gateway.auth.token and agents.defaults.model.primary from the
        same materialized config file the CLI path already reads (worker-agent
        mounts OPENCLAW_CONFIG_PATH read-only). Reused, not re-issued."""
        if self._token is not None:
            return
        if not self._config_path:
            raise RuntimeError("OPENCLAW_CONFIG_PATH not set — cannot resolve gateway auth token")
        with open(self._config_path, encoding="utf-8") as f:
            config = json.load(f)
        token = config.get("gateway", {}).get("auth", {}).get("token", "")
        if not token:
            raise RuntimeError(f"gateway.auth.token missing from {self._config_path}")
        self._token = token

        model_ref = config.get("agents", {}).get("defaults", {}).get("model", {}).get("primary", "")
        # Strip the "provider/" prefix (e.g. "openai/gpt-5.4-mini" -> "gpt-5.4-mini")
        # to match usage_writer._PRICING's bare model-name prefixes.
        self._model = model_ref.split("/", 1)[1] if "/" in model_ref else model_ref

    def is_available(self) -> bool:
        try:
            resp = httpx.get(f"{self._base_url}/readyz", timeout=5.0)
            return resp.status_code == 200 and resp.json().get("ready") is True
        except (httpx.HTTPError, ValueError):
            return False

    def invoke(self, spec: AgentInvocationSpec, *, message_override: str | None = None) -> AgentInvocationResult:
        self._load_gateway_config()
        message = message_override or build_invocation_message(spec)

        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "x-openclaw-agent-id": spec.agent_id,
            "x-openclaw-session-key": spec.session_key,
        }
        body = {
            "model": f"openclaw/{spec.agent_id}",
            "messages": [{"role": "user", "content": message}],
        }

        start = time.monotonic()
        try:
            resp = httpx.post(
                f"{self._base_url}/v1/chat/completions",
                headers=headers,
                json=body,
                timeout=httpx.Timeout(spec.timeout_seconds, connect=self._connect_timeout),
            )
            duration = time.monotonic() - start
        except httpx.TimeoutException:
            duration = time.monotonic() - start
            logger.error(
                "Agent invocation timed out after %.1fs: invocation_id=%s",
                duration, spec.invocation_id,
            )
            return AgentInvocationResult(
                invocation_id=spec.invocation_id,
                exit_code=1,
                stdout="",
                stderr="request timed out",
                duration_seconds=duration,
                timed_out=True,
            )
        except httpx.HTTPError as exc:
            duration = time.monotonic() - start
            logger.error(
                "Agent invocation transport error: invocation_id=%s error=%s",
                spec.invocation_id, exc,
            )
            return AgentInvocationResult(
                invocation_id=spec.invocation_id,
                exit_code=1,
                stdout="",
                stderr=f"{type(exc).__name__}: {exc}",
                duration_seconds=duration,
            )

        raw_text = resp.text
        if resp.status_code != 200:
            logger.warning(
                "Agent invocation returned HTTP %d: invocation_id=%s body=%s",
                resp.status_code, spec.invocation_id, raw_text[:500],
            )
            return AgentInvocationResult(
                invocation_id=spec.invocation_id,
                exit_code=1,
                stdout=raw_text,
                stderr=f"HTTP {resp.status_code}",
                duration_seconds=duration,
            )

        try:
            payload = resp.json()
        except ValueError as exc:
            return AgentInvocationResult(
                invocation_id=spec.invocation_id,
                exit_code=1,
                stdout=raw_text,
                stderr=f"response was not valid JSON: {exc}",
                duration_seconds=duration,
            )

        logger.info(
            "Agent invocation completed: duration=%.1fs invocation_id=%s",
            duration, spec.invocation_id,
        )

        # A 200 OK here means the LLM call already round-tripped and was
        # billed — an unexpected payload shape must not raise past this
        # point, or an already-successful, already-paid-for response gets
        # discarded entirely (content included) instead of just losing its
        # usage figure.
        try:
            usage = self._extract_usage(payload)
        except Exception:
            logger.warning(
                "Failed to extract usage from a 200 OK response (invocation_id=%s) — "
                "continuing without usage; the underlying call was still billed.",
                spec.invocation_id,
                exc_info=True,
            )
            usage = None

        return AgentInvocationResult(
            invocation_id=spec.invocation_id,
            exit_code=0,
            stdout=raw_text,
            stderr="",
            duration_seconds=duration,
            timed_out=False,
            tool_activity_summary_path=None,
            usage=usage,
        )

    def _extract_usage(self, payload: object) -> AgentUsageSummary | None:
        if not isinstance(payload, dict):
            return None
        usage = payload.get("usage")
        if not isinstance(usage, dict):
            return None
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)
        if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
            return None
        if input_tokens == 0 and output_tokens == 0:
            return None
        prompt_details = usage.get("prompt_tokens_details")
        completion_details = usage.get("completion_tokens_details")
        cache_read = prompt_details.get("cached_tokens", 0) if isinstance(prompt_details, dict) else 0
        reasoning = (
            completion_details.get("reasoning_tokens", 0)
            if isinstance(completion_details, dict)
            else 0
        )
        return AgentUsageSummary(
            model=self._model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read if isinstance(cache_read, int) else 0,
            cache_write_tokens=0,
            reasoning_tokens=reasoning if isinstance(reasoning, int) else 0,
            session_file=None,
            llm_calls=1,
        )


# ---------------------------------------------------------------------------
# Factory — mirrors create_runtime() in openclaw.py
# ---------------------------------------------------------------------------


def create_http_runtime() -> OpenClawHttpRuntime:
    """Build an OpenClawHttpRuntime using environment defaults.

    Falls back to OPENCLAW_GATEWAY_HTTP_URL and OPENCLAW_CONFIG_PATH
    environment variables if not provided explicitly.
    """
    return OpenClawHttpRuntime()

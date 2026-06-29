"""
OpenClawGatewayRuntime — gateway client implementation of AgentRuntime.

Architecture role
-----------------
This class is a *client* to the openclaw-gateway container/process.  It does
NOT embed or spawn an OpenClaw runtime of its own.  The worker container is
responsible only for:

  1. Writing input.json to the shared agent_artifacts volume.
  2. Invoking the OpenClaw CLI as a thin client shim that routes the call
     through the running openclaw-gateway daemon (via OPENCLAW_STATE_DIR socket).
  3. Reading output_manifest.json after the gateway has completed the run.

The openclaw-gateway container is the sole OpenClaw execution host:
  - Holds agent workspace, skills, session state
  - Enforces exec-approvals.json
  - Runs approved wrapper scripts inside its own sandbox

The gateway is a hard runtime dependency.  ``is_available()`` verifies it
before any invocation attempt.

Usage
-----
Use ``create_runtime()`` as the single construction point for all worker
task handlers — do not instantiate ``OpenClawGatewayRuntime`` directly.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import subprocess
import time

from packages.contracts.agents.invocation import (
    AgentInvocationResult,
    AgentInvocationSpec,
    AgentUsageSummary,
)
from packages.contracts.agents.tool_activity import ToolActivitySummary, ToolCallRecord
from packages.infrastructure.agent_runtime.base import AgentRuntime

logger = logging.getLogger(__name__)

_DEFAULT_OPENCLAW_BIN = os.environ.get("OPENCLAW_BIN", "openclaw")
_DEFAULT_STATE_DIR = os.environ.get("OPENCLAW_STATE_DIR")
_TOOL_ACTIVITY_SUMMARY_FILENAME = "gateway_tool_activity.json"
_SENTINEL = object()


class OpenClawGatewayRuntime(AgentRuntime):
    """
    Invokes OpenClaw agents via the openclaw-gateway daemon.

    The CLI binary (``openclaw agent``) acts as a thin client: it locates the
    running gateway via OPENCLAW_STATE_DIR and forwards the invocation.  All
    exec, state, and session management happen inside the gateway process — not
    in this worker container.

    Note: ``openclaw agent`` (2026.6+) does not support a ``--config`` flag.
    Config is loaded by the gateway process itself via OPENCLAW_CONFIG_PATH.
    The worker only needs OPENCLAW_STATE_DIR to locate the gateway socket.

    The agent reads its task from input_spec_path (written by the caller
    before ``invoke``).  The agent writes its output to output_manifest_path
    (read by the caller after ``invoke``).
    """

    def __init__(
        self,
        openclaw_bin: str = _DEFAULT_OPENCLAW_BIN,
        state_dir: str | None = None,
    ) -> None:
        self._bin = openclaw_bin
        self._state_dir = state_dir or _DEFAULT_STATE_DIR

    def is_available(self) -> bool:
        """Return True if the openclaw CLI binary is reachable."""
        try:
            result = subprocess.run(
                [self._bin, "--version"],
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def invoke(self, spec: AgentInvocationSpec, *, message_override: str | None = None) -> AgentInvocationResult:
        message = message_override or self._build_invocation_message(spec)

        cmd = [
            self._bin,
            "agent",
            "--agent", spec.agent_id,
            "--session-key", spec.session_key,
            "--json",
            "--message", message,
        ]

        env = _build_env(self._state_dir)

        logger.info(
            "Invoking OpenClaw agent via gateway: agent_id=%s session_key=%s invocation_id=%s%s",
            spec.agent_id,
            spec.session_key,
            spec.invocation_id,
            " (continuation)" if message_override else "",
        )

        start = time.monotonic()
        timed_out = False

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=spec.timeout_seconds,
                env=env,
            )
            duration = time.monotonic() - start

        except subprocess.TimeoutExpired as exc:
            duration = time.monotonic() - start
            timed_out = True
            logger.error(
                "Agent invocation timed out after %.1fs: invocation_id=%s",
                duration,
                spec.invocation_id,
            )
            return AgentInvocationResult(
                invocation_id=spec.invocation_id,
                exit_code=1,
                stdout=exc.stdout or "",
                stderr=exc.stderr or "",
                duration_seconds=duration,
                timed_out=True,
            )

        logger.info(
            "Agent invocation completed: exit_code=%d duration=%.1fs invocation_id=%s",
            result.returncode,
            duration,
            spec.invocation_id,
        )

        payload, _ = _parse_stdout_json(result.stdout)
        summary = _build_tool_activity_summary(spec, result.stdout, payload=payload)
        summary_path = _write_tool_activity_summary(spec, summary)
        usage = _extract_agent_usage(payload, summary.session_file)

        transport_rejection_reason = _transport_rejection_reason(
            summary.transport, summary.fallback_from
        )
        effective_exit_code = result.returncode
        effective_stderr = result.stderr

        if result.returncode == 0 and transport_rejection_reason:
            logger.error(
                "Rejecting invocation due to non-gateway transport: invocation_id=%s reason=%s",
                spec.invocation_id,
                transport_rejection_reason,
            )
            effective_exit_code = 1
            effective_stderr = _append_stderr(
                result.stderr, f"Gateway transport validation failed: {transport_rejection_reason}"
            )

        if effective_exit_code != 0:
            logger.warning(
                "Agent exited non-zero: %s\nstderr: %s",
                spec.invocation_id,
                effective_stderr[:500],
            )

        return AgentInvocationResult(
            invocation_id=spec.invocation_id,
            exit_code=effective_exit_code,
            stdout=result.stdout,
            stderr=effective_stderr,
            duration_seconds=duration,
            timed_out=timed_out,
            tool_activity_summary_path=summary_path,
            usage=usage,
        )

    def _build_invocation_message(self, spec: AgentInvocationSpec) -> str:
        """
        Build the invocation message passed to the agent.

        The full task spec is embedded inline so the agent never needs to read
        a file from outside its workspace sandbox.  The output_manifest_path is
        still included as a write target because the agent uses approved exec
        wrappers (career_write_manifest.py) to produce it — those scripts run
        inside the gateway and have access to /app/data/agent_artifacts.
        """
        # Read the task spec that the caller wrote to the shared volume.
        # Embedding it here prevents the codex embedded-runner from needing to
        # sandbox-escape to /app/data/agent_artifacts to read the file.
        try:
            task_spec_json = Path(spec.input_spec_path).read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning(
                "Could not read input_spec_path for inline embedding: %s — "
                "agent will be given path only (may fail in sandbox)", exc
            )
            task_spec_json = None

        if task_spec_json:
            spec_block = (
                f"Your task spec (full JSON — do NOT read from file, use this directly):\n\n"
                f"```json\n{task_spec_json}\n```"
            )
        else:
            spec_block = (
                f"Read your task spec from:\n"
                f"  {spec.input_spec_path}"
            )

        evidence_paragraph = _evidence_instructions(spec.agent_id)

        return (
            f"Agent: {spec.agent_id}\n"
            f"Invocation ID: {spec.invocation_id}\n\n"
            f"{spec_block}\n\n"
            f"Call career_write_manifest before stopping. The wrapper writes the "
            f"platform manifest to the canonical path derived from your task spec "
            f"(expected: {spec.output_manifest_path}). Do not pass a hand-copied "
            f"manifest path to --output.\n\n"
            f"{evidence_paragraph}\n\n"
            f"Follow the active skill instructions.\n"
            f"Do not write to the database.\n"
            f"Do not modify files outside your designated run directory.\n"
            f"Stop after writing the manifest."
        )


def _evidence_instructions(agent_id: str) -> str:
    """Return the agent-type-specific evidence paragraph for the invocation message."""
    if agent_id == "career-reflect-agent":
        return (
            "This is a real production run. You MUST analyze the provided run "
            "artifacts (coverage report, search ledger, candidate pool) before "
            "writing the manifest. Do NOT write placeholder or mock output. "
            "Do NOT mark status as completed or partial without genuine analysis "
            "of the prior run's results. "
            "strategy_patch.json MUST be a flat object with only the 7 allowed "
            "fields (effective_sources, avoid_sources, effective_query_patterns, "
            "avoid_query_patterns, coverage_by_role_category, key_learnings, "
            "recommended_next_searches). Do NOT wrap it in run_id, patches, "
            "operations, or other metadata."
        )
    return (
        "This is a real production run. You MUST perform genuine discovery "
        "actions (web_search, web_fetch, or approved exec wrappers) before "
        "writing the manifest. Do NOT write placeholder or mock output. "
        "Do NOT mark status as completed or partial without real tool calls "
        "that support it."
    )


# ---------------------------------------------------------------------------
# Backward-compatible alias (old name kept for any direct import that may
# exist in tests or scripts outside the main handlers)
# ---------------------------------------------------------------------------

OpenClawRuntime = OpenClawGatewayRuntime


# ---------------------------------------------------------------------------
# Factory — single construction point for all worker task handlers
# ---------------------------------------------------------------------------


def create_runtime(
    openclaw_bin: str | None = None,
    state_dir: str | None = None,
) -> OpenClawGatewayRuntime:
    """
    Build an ``OpenClawGatewayRuntime`` using environment defaults.

    All worker handlers should call this instead of instantiating the class
    directly.  This makes it trivial to swap the runtime implementation
    (e.g. future HTTP-based gateway client) from a single location.

    Parameters fall back to ``OPENCLAW_BIN`` and ``OPENCLAW_STATE_DIR``
    environment variables if not provided explicitly.
    Config loading is handled by the gateway process via OPENCLAW_CONFIG_PATH —
    the worker client does not pass --config to the CLI.
    """
    return OpenClawGatewayRuntime(
        openclaw_bin=openclaw_bin or _DEFAULT_OPENCLAW_BIN,
        state_dir=state_dir or _DEFAULT_STATE_DIR,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_env(state_dir: str | None) -> dict[str, str] | None:
    """
    Return a subprocess environment that includes OPENCLAW_STATE_DIR when set.

    The OpenClaw CLI uses OPENCLAW_STATE_DIR to locate the gateway daemon
    socket.  Passing it explicitly through the subprocess env ensures the
    correct gateway is used even if the OS-level env differs.
    """
    if not state_dir:
        return None

    env = os.environ.copy()
    env["OPENCLAW_STATE_DIR"] = state_dir
    return env


def _append_stderr(stderr: str, message: str) -> str:
    stderr = (stderr or "").strip()
    if not stderr:
        return message
    return f"{stderr}\n{message}"


def _transport_rejection_reason(
    transport: str | None,
    fallback_from: str | None,
) -> str | None:
    if transport and transport.lower() == "embedded":
        return "meta.transport=embedded is not allowed in gateway-only mode"
    if fallback_from and fallback_from.lower() == "gateway":
        return "meta.fallbackFrom=gateway indicates fallback to embedded runtime"
    return None


def _build_tool_activity_summary(
    spec: AgentInvocationSpec,
    stdout: str,
    *,
    payload: object | None = _SENTINEL,
) -> ToolActivitySummary:
    if payload is _SENTINEL:
        payload, parse_errors = _parse_stdout_json(stdout)
    else:
        parse_errors: list[str] = []
    transport, fallback_from, session_file = _extract_runtime_meta(payload)

    payload_tool_calls = _extract_tool_calls_from_payload(payload)
    session_tool_calls: list[ToolCallRecord] = []
    if not payload_tool_calls and session_file:
        session_tool_calls, session_errors = _extract_tool_calls_from_session_file(session_file)
        parse_errors.extend(session_errors)

    tool_calls = _dedupe_tool_calls(payload_tool_calls or session_tool_calls)
    return ToolActivitySummary(
        invocation_id=spec.invocation_id,
        session_key=spec.session_key,
        transport=transport,
        fallback_from=fallback_from,
        session_file=session_file,
        tool_call_count=len(tool_calls),
        tool_calls=tool_calls,
        parse_errors=parse_errors,
    )


def _write_tool_activity_summary(spec: AgentInvocationSpec, summary: ToolActivitySummary) -> str:
    summary_path = Path(spec.output_manifest_path).parent / _TOOL_ACTIVITY_SUMMARY_FILENAME
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(summary.model_dump_json(indent=2))
    return str(summary_path)


def _parse_stdout_json(stdout: str) -> tuple[object | None, list[str]]:
    parse_errors: list[str] = []
    raw = (stdout or "").strip()
    if not raw:
        return None, parse_errors

    try:
        return json.loads(raw), parse_errors
    except json.JSONDecodeError as exc:
        parse_errors.append(f"stdout is not a single JSON document: {exc}")

    # Some CLIs may print extra non-JSON lines; fall back to the last JSON-looking line.
    for line in reversed(raw.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            return json.loads(line), parse_errors
        except json.JSONDecodeError:
            continue

    parse_errors.append("could not parse JSON payload from stdout")
    return None, parse_errors


def _extract_runtime_meta(payload: object | None) -> tuple[str | None, str | None, str | None]:
    transport = _find_first_key(payload, {"transport"})
    fallback_from = _find_first_key(payload, {"fallbackFrom", "fallback_from"})
    session_file = _find_first_key(payload, {"sessionFile", "session_file"})
    return _to_str(transport), _to_str(fallback_from), _to_str(session_file)


def _to_str(value: object | None) -> str | None:
    if isinstance(value, str):
        return value
    return None


def _find_first_key(payload: object | None, keys: set[str]) -> object | None:
    if isinstance(payload, dict):
        for k, value in payload.items():
            if k in keys:
                return value
            nested = _find_first_key(value, keys)
            if nested is not None:
                return nested
        return None
    if isinstance(payload, list):
        for item in payload:
            nested = _find_first_key(item, keys)
            if nested is not None:
                return nested
    return None


def _extract_tool_calls_from_payload(payload: object | None) -> list[ToolCallRecord]:
    if payload is None:
        return []

    tool_calls: list[ToolCallRecord] = []
    for node in _iter_nodes(payload):
        if not isinstance(node, dict):
            continue

        calls = node.get("tool_calls")
        if isinstance(calls, list):
            for call in calls:
                rec = _record_from_tool_call_dict(call, source="gateway_payload")
                if rec:
                    tool_calls.append(rec)
    return tool_calls


def _extract_tool_calls_from_session_file(
    session_file: str,
) -> tuple[list[ToolCallRecord], list[str]]:
    parse_errors: list[str] = []
    path = Path(session_file)
    if not path.exists():
        return [], [f"session file does not exist: {session_file}"]

    tool_calls: list[ToolCallRecord] = []
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue

            for node in _iter_nodes(payload):
                if not isinstance(node, dict):
                    continue
                node_type = str(node.get("type", "")).lower()
                if node_type not in {"toolcall", "tool_call"}:
                    continue
                rec = _record_from_tool_call_dict(node, source="gateway_session")
                if rec:
                    tool_calls.append(rec)
    except OSError as exc:
        parse_errors.append(f"failed to read session file {session_file}: {exc}")

    return tool_calls, parse_errors


def _record_from_tool_call_dict(
    call: object,
    *,
    source: str,
) -> ToolCallRecord | None:
    if not isinstance(call, dict):
        return None

    tool_raw = (
        call.get("tool")
        or call.get("tool_name")
        or call.get("toolName")
        or call.get("name")
    )
    if not isinstance(tool_raw, str):
        return None

    args = call.get("arguments") or call.get("args") or call.get("input")
    tool = _normalize_tool_name(tool_raw, args)
    status = str(call.get("status", "unknown"))
    timestamp = _to_str(call.get("timestamp"))

    output_artifact = None
    if isinstance(call.get("output_artifact"), str):
        output_artifact = call["output_artifact"]

    return ToolCallRecord(
        tool=tool,
        timestamp=timestamp,
        status=status,
        source=source,
        output_artifact=output_artifact,
    )


def _normalize_tool_name(tool_name: str, args: object) -> str:
    normalized = tool_name.strip().lower()
    if normalized not in {"exec", "shell", "bash"}:
        return normalized

    command = _extract_command_text(args)
    wrapper_map = {
        "career_fetch_source.py": "career_fetch_source",
        "career_log_candidates.py": "career_log_candidates",
        "career_write_manifest.py": "career_write_manifest",
        "career_search_status.py": "career_search_status",
    }
    for needle, tool in wrapper_map.items():
        if needle in command:
            return tool
    return normalized


def _extract_command_text(args: object) -> str:
    if isinstance(args, str):
        return args
    if isinstance(args, list):
        return " ".join(str(x) for x in args)
    if isinstance(args, dict):
        command_bits: list[str] = []
        for key in ("command", "cmd", "bash", "script"):
            value = args.get(key)
            if isinstance(value, str):
                command_bits.append(value)
            elif isinstance(value, list):
                command_bits.extend(str(x) for x in value)
        if not command_bits:
            command_bits.append(json.dumps(args, ensure_ascii=True))
        return " ".join(command_bits)
    return ""


def _iter_nodes(payload: object) -> list[object]:
    nodes: list[object] = []
    stack: list[object] = [payload]
    while stack:
        item = stack.pop()
        nodes.append(item)
        if isinstance(item, dict):
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    return nodes


def _dedupe_tool_calls(tool_calls: list[ToolCallRecord]) -> list[ToolCallRecord]:
    seen: set[tuple[str, str, str, str]] = set()
    unique: list[ToolCallRecord] = []
    for call in tool_calls:
        key = (
            call.tool,
            call.timestamp or "",
            call.status,
            call.source,
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(call)
    return unique


# ---------------------------------------------------------------------------
# Agent LLM usage extraction
# ---------------------------------------------------------------------------


def _normalize_tokens(usage: dict) -> tuple[int, int, int, int, int]:
    """Normalize provider-varying field names into (input, output, cache_read, cache_write, reasoning).

    Handles OpenAI (input/output), Anthropic (input_tokens/output_tokens),
    and legacy (prompt_tokens/completion_tokens) naming conventions.
    """
    inp = usage.get("input") or usage.get("input_tokens") or usage.get("inputTokens") or usage.get("prompt_tokens") or 0
    out = usage.get("output") or usage.get("output_tokens") or usage.get("outputTokens") or usage.get("completion_tokens") or 0
    cache_r = usage.get("cacheRead") or usage.get("cache_read") or usage.get("cache_read_tokens") or 0
    if isinstance(usage.get("prompt_tokens_details"), dict):
        cache_r = cache_r or usage["prompt_tokens_details"].get("cached_tokens", 0)
    cache_w = usage.get("cacheWrite") or usage.get("cache_write") or usage.get("cache_write_tokens") or 0
    reasoning = usage.get("reasoningTokens") or usage.get("reasoning_tokens") or 0
    return int(inp), int(out), int(cache_r), int(cache_w), int(reasoning)


def _aggregate_session_usage(
    session_file: str | None,
) -> tuple[int, int, int, int, int, int, str]:
    """Sum per-message usage from session JSONL.

    Returns (input, output, cache_read, cache_write, reasoning, llm_calls, model).
    """
    if not session_file:
        return 0, 0, 0, 0, 0, 0, ""
    path = Path(session_file)
    if not path.exists():
        return 0, 0, 0, 0, 0, 0, ""

    total_inp = total_out = total_cr = total_cw = total_r = llm_calls = 0
    model = ""
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict) or obj.get("type") != "message":
                continue
            msg = obj.get("message", {})
            if not isinstance(msg, dict):
                continue
            usage = msg.get("usage")
            if not isinstance(usage, dict):
                continue
            llm_calls += 1
            inp, out, cr, cw, r = _normalize_tokens(usage)
            total_inp += inp
            total_out += out
            total_cr += cr
            total_cw += cw
            total_r += r
            if not model:
                model = str(msg.get("model", ""))
    except OSError:
        pass
    return total_inp, total_out, total_cr, total_cw, total_r, llm_calls, model


def _extract_agent_usage(
    payload: object | None,
    session_file: str | None,
) -> AgentUsageSummary | None:
    """Extract LLM usage from stdout JSON → result.meta.agentMeta, falling
    back to per-message aggregation from the session JSONL file."""

    # --- primary path: agentMeta.usage from stdout payload ---
    agent_meta = None
    if isinstance(payload, dict):
        result = payload.get("result")
        if isinstance(result, dict):
            meta = result.get("meta")
            if isinstance(meta, dict):
                agent_meta = meta.get("agentMeta")

    if isinstance(agent_meta, dict):
        usage = agent_meta.get("usage")
        if isinstance(usage, dict):
            model = str(agent_meta.get("model", ""))
            inp, out, cache_r, cache_w, reasoning = _normalize_tokens(usage)
            if inp > 0 or out > 0:
                _, _, _, _, _, llm_calls, _ = _aggregate_session_usage(session_file)
                return AgentUsageSummary(
                    model=model,
                    input_tokens=inp,
                    output_tokens=out,
                    cache_read_tokens=cache_r,
                    cache_write_tokens=cache_w,
                    reasoning_tokens=reasoning,
                    session_file=session_file,
                    llm_calls=llm_calls,
                )

    # --- fallback: aggregate from session JSONL ---
    inp, out, cache_r, cache_w, reasoning, llm_calls, model = (
        _aggregate_session_usage(session_file)
    )
    if inp == 0 and out == 0:
        logger.warning(
            "Agent usage unavailable: agentMeta missing and session file "
            "has no token data (session_file=%s)",
            session_file,
        )
        return None

    logger.info(
        "Agent usage recovered from session file (agentMeta unavailable): "
        "input=%d output=%d calls=%d session_file=%s",
        inp, out, llm_calls, session_file,
    )
    return AgentUsageSummary(
        model=model,
        input_tokens=inp,
        output_tokens=out,
        cache_read_tokens=cache_r,
        cache_write_tokens=cache_w,
        reasoning_tokens=reasoning,
        session_file=session_file,
        llm_calls=llm_calls,
    )

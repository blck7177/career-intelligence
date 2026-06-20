"""
OpenClawRuntime — concrete AgentRuntime implementation.

Invokes the OpenClaw CLI as a subprocess.
The gateway is expected to be running and accessible (see infra/docker/openclaw.Dockerfile).
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from pathlib import Path

from packages.contracts.agents.invocation import AgentInvocationResult, AgentInvocationSpec
from packages.infrastructure.agent_runtime.base import AgentRuntime
from packages.infrastructure.agent_runtime.errors import (
    AgentInvocationError,
    AgentTimeoutError,
)

logger = logging.getLogger(__name__)

_DEFAULT_OPENCLAW_BIN = os.environ.get("OPENCLAW_BIN", "openclaw")


class OpenClawRuntime(AgentRuntime):
    """
    Invokes OpenClaw agents via the OpenClaw CLI.

    The agent reads its task from input_spec_path (written by caller before invoke).
    The agent writes its output to output_manifest_path.
    Caller is responsible for reading and validating the manifest.
    """

    def __init__(
        self,
        openclaw_bin: str = _DEFAULT_OPENCLAW_BIN,
        config_path: str | None = None,
    ) -> None:
        self._bin = openclaw_bin
        self._config_path = config_path or os.environ.get("OPENCLAW_CONFIG_PATH")

    def is_available(self) -> bool:
        try:
            result = subprocess.run(
                [self._bin, "--version"],
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def invoke(self, spec: AgentInvocationSpec) -> AgentInvocationResult:
        message = self._build_invocation_message(spec)

        cmd = [
            self._bin,
            "agent",
            "--agent", spec.agent_id,
            "--session-key", spec.session_key,
            "--json",
            "--message", message,
        ]

        if self._config_path:
            cmd += ["--config", self._config_path]

        logger.info(
            "Invoking OpenClaw agent: agent_id=%s session_key=%s invocation_id=%s",
            spec.agent_id,
            spec.session_key,
            spec.invocation_id,
        )

        start = time.monotonic()
        timed_out = False

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=spec.timeout_seconds,
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

        if result.returncode != 0:
            logger.warning(
                "Agent exited non-zero: %s\nstderr: %s",
                spec.invocation_id,
                result.stderr[:500],
            )

        return AgentInvocationResult(
            invocation_id=spec.invocation_id,
            exit_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            duration_seconds=duration,
            timed_out=timed_out,
        )

    def _build_invocation_message(self, spec: AgentInvocationSpec) -> str:
        """
        Build the short invocation message passed to the agent.
        The agent reads its full task from input_spec_path.
        """
        return (
            f"You are executing a bounded task.\n\n"
            f"Agent: {spec.agent_id}\n"
            f"Invocation ID: {spec.invocation_id}\n\n"
            f"Read your task spec from:\n"
            f"  {spec.input_spec_path}\n\n"
            f"Write your output manifest to:\n"
            f"  {spec.output_manifest_path}\n\n"
            f"Follow the active skill instructions.\n"
            f"Do not write to the database.\n"
            f"Do not modify files outside your designated run directory.\n"
            f"Stop after writing the manifest."
        )

"""Agent runtime error types."""


class AgentRuntimeError(Exception):
    """Base class for agent runtime errors."""


class AgentInvocationError(AgentRuntimeError):
    """Agent exited with non-zero exit code."""

    def __init__(self, invocation_id: str, exit_code: int, stderr: str) -> None:
        super().__init__(
            f"Agent invocation {invocation_id} failed with exit_code={exit_code}"
        )
        self.invocation_id = invocation_id
        self.exit_code = exit_code
        self.stderr = stderr


class AgentTimeoutError(AgentRuntimeError):
    """Agent invocation exceeded timeout."""

    def __init__(self, invocation_id: str, timeout_seconds: int) -> None:
        super().__init__(
            f"Agent invocation {invocation_id} timed out after {timeout_seconds}s"
        )
        self.invocation_id = invocation_id
        self.timeout_seconds = timeout_seconds


class AgentManifestError(AgentRuntimeError):
    """Agent output manifest is missing or invalid."""

    def __init__(self, invocation_id: str, reason: str) -> None:
        super().__init__(
            f"Agent invocation {invocation_id} produced invalid manifest: {reason}"
        )
        self.invocation_id = invocation_id
        self.reason = reason

"""
AgentRuntime interface.

Business code depends only on this interface.
The concrete implementation (OpenClawRuntime) is in openclaw.py.
Future implementations: LangGraphRuntime, TemporalRuntime, etc.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from packages.contracts.agents.invocation import AgentInvocationResult, AgentInvocationSpec


class AgentRuntime(ABC):
    @abstractmethod
    def invoke(self, spec: AgentInvocationSpec) -> AgentInvocationResult:
        """
        Execute a bounded agent task.

        Writes input.json to spec.input_spec_path before calling the agent.
        Reads output_manifest.json from spec.output_manifest_path after.
        Returns raw execution result; caller is responsible for validation.
        """
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Health check: can this runtime accept invocations right now?"""
        ...

"""
LLM client — thin wrapper around the OpenAI chat completion API.

Rules:
  - Only this module calls the OpenAI API.
  - domain/ must not import this module.
  - All prompts are passed in as plain strings; no prompt logic lives here.
  - Errors are re-raised as LLMCallError for callers to handle.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "gpt-4o-mini"
_DEFAULT_MAX_TOKENS = 4096
_DEFAULT_TEMPERATURE = 0.3


class LLMCallError(Exception):
    """Raised when the LLM API call fails or returns an unusable response."""


@dataclass
class LLMMessage:
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass
class LLMResponse:
    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass
class LLMClient:
    """
    Stateless LLM client.
    Instantiate once per worker process; thread-safe for read-only operations.
    """

    model: str = field(default_factory=lambda: os.environ.get("LLM_MODEL", _DEFAULT_MODEL))
    max_tokens: int = _DEFAULT_MAX_TOKENS
    temperature: float = _DEFAULT_TEMPERATURE
    _api_key: str | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        self._api_key = os.environ.get("OPENAI_API_KEY")

    def _get_client(self):  # type: ignore[return]
        try:
            import openai
        except ImportError as exc:
            raise LLMCallError(
                "openai package is not installed. Add it to pyproject.toml."
            ) from exc

        if not self._api_key:
            raise LLMCallError(
                "OPENAI_API_KEY environment variable is not set."
            )

        return openai.OpenAI(api_key=self._api_key)

    def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> LLMResponse:
        """
        Make a chat completion call.

        Args:
            messages:    Conversation messages (system + user at minimum).
            model:       Override default model.
            max_tokens:  Override default max_tokens.
            temperature: Override default temperature.

        Returns:
            LLMResponse with content and token usage.

        Raises:
            LLMCallError on API failure.
        """
        client = self._get_client()

        api_messages = [{"role": m.role, "content": m.content} for m in messages]
        _model = model or self.model
        _max_tokens = max_tokens or self.max_tokens
        _temperature = temperature if temperature is not None else self.temperature

        logger.info(
            "LLM call: model=%s max_tokens=%d messages=%d",
            _model,
            _max_tokens,
            len(api_messages),
        )

        try:
            response = client.chat.completions.create(
                model=_model,
                messages=api_messages,  # type: ignore[arg-type]
                max_tokens=_max_tokens,
                temperature=_temperature,
            )
        except Exception as exc:
            raise LLMCallError(f"OpenAI API call failed: {exc}") from exc

        choice = response.choices[0]
        content = choice.message.content or ""
        usage = response.usage

        logger.info(
            "LLM response: tokens=%d/%d finish=%s",
            usage.prompt_tokens if usage else 0,
            usage.completion_tokens if usage else 0,
            choice.finish_reason,
        )

        return LLMResponse(
            content=content,
            model=response.model,
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            total_tokens=usage.total_tokens if usage else 0,
        )

    def complete_simple(
        self,
        system_prompt: str,
        user_prompt: str,
        **kwargs,
    ) -> str:
        """Convenience wrapper for simple system+user calls. Returns content string."""
        messages = [
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content=user_prompt),
        ]
        response = self.complete(messages, **kwargs)
        return response.content


# Module-level singleton for worker reuse
_default_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    """Return a module-level LLMClient singleton (lazy init)."""
    global _default_client
    if _default_client is None:
        _default_client = LLMClient()
    return _default_client

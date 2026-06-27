"""
LLM client — thin wrapper around the OpenAI chat completion API.

Rules:
  - Only this module calls the OpenAI API.
  - domain/ must not import this module.
  - All prompts are passed in as plain strings; no prompt logic lives here.
  - Errors are re-raised as LLMCallError for callers to handle.

Structured output:
  Use complete_structured() for schema-constrained extraction tasks.
  This uses OpenAI's response_format=json_schema with strict=True, which
  applies constrained decoding at the token level — schema violations are
  mathematically impossible (not just statistically unlikely).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from pydantic import BaseModel as PydanticBaseModel

T = TypeVar("T", bound="PydanticBaseModel")

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "gpt-4o-mini"
_DEFAULT_MAX_TOKENS = 4096
_DEFAULT_TEMPERATURE = 0.3

# Models that require max_completion_tokens instead of max_tokens, and
# that do not accept a temperature parameter.
_REASONING_MODEL_PREFIXES = ("o1", "o3", "o4", "gpt-5")


def _is_reasoning_model(model: str) -> bool:
    """Return True for models that use max_completion_tokens and no temperature."""
    return any(model.startswith(p) for p in _REASONING_MODEL_PREFIXES)


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
            kwargs: dict = {
                "model": _model,
                "messages": api_messages,
            }
            if _is_reasoning_model(_model):
                kwargs["max_completion_tokens"] = _max_tokens
            else:
                kwargs["max_tokens"] = _max_tokens
                kwargs["temperature"] = _temperature
            response = client.chat.completions.create(**kwargs)  # type: ignore[arg-type]
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

    def complete_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: "type[T]",
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> "T":
        """
        Schema-constrained chat completion using OpenAI Structured Outputs.

        Uses response_format=json_schema with strict=True, which applies
        constrained decoding at the token level. The returned object is already
        validated against response_schema — no manual JSON parsing required.

        Args:
            system_prompt:   Instruction text (defines semantic policy).
            user_prompt:     Data payload (should use XML data blocks for
                             untrusted input to prevent prompt injection).
            response_schema: Pydantic BaseModel subclass defining the contract.
            model:           Override default model.
            temperature:     Override default temperature.
            max_tokens:      Override default max_tokens.

        Returns:
            A fully-validated instance of response_schema.

        Raises:
            LLMCallError on API failure or if the model refuses to produce output.
        """
        client = self._get_client()

        _model = model or self.model
        _temperature = temperature if temperature is not None else self.temperature
        _max_tokens = max_tokens or self.max_tokens

        api_messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        logger.info(
            "LLM structured call: model=%s schema=%s max_tokens=%d",
            _model,
            response_schema.__name__,
            _max_tokens,
        )

        try:
            parse_kwargs: dict = {
                "model": _model,
                "messages": api_messages,
                "response_format": response_schema,
            }
            if _is_reasoning_model(_model):
                parse_kwargs["max_completion_tokens"] = _max_tokens
            else:
                parse_kwargs["max_tokens"] = _max_tokens
                parse_kwargs["temperature"] = _temperature
            response = client.beta.chat.completions.parse(**parse_kwargs)  # type: ignore[arg-type]
        except Exception as exc:
            raise LLMCallError(
                f"OpenAI structured output call failed: {exc}"
            ) from exc

        choice = response.choices[0]
        usage = response.usage

        logger.info(
            "LLM structured response: tokens=%d/%d finish=%s",
            usage.prompt_tokens if usage else 0,
            usage.completion_tokens if usage else 0,
            choice.finish_reason,
        )

        if choice.finish_reason == "length":
            raise LLMCallError(
                f"LLM output truncated (finish_reason=length). "
                f"Increase max_tokens or simplify the request. "
                f"Schema: {response_schema.__name__}"
            )

        parsed = choice.message.parsed
        if parsed is None:
            raise LLMCallError(
                f"LLM returned no parsed output for schema {response_schema.__name__}. "
                f"finish_reason={choice.finish_reason!r}"
            )

        return parsed  # type: ignore[return-value]


# Module-level singleton for worker reuse
_default_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    """Return a module-level LLMClient singleton (lazy init)."""
    global _default_client
    if _default_client is None:
        _default_client = LLMClient()
    return _default_client

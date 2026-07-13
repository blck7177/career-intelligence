"""
Tests for LLMClient.complete_structured() usage-emission on failure paths.

Regression coverage for a real accounting gap found in a 2026-07-12 audit:
complete_structured() had four raise points (finish_reason=length,
finish_reason=content_filter, refusal, JSON-parse failure) that fired AFTER
OpenAI had already generated and billed tokens but BEFORE _emit_usage() was
called — so a truncated/filtered/refused/malformed response left real spend
completely unrecorded in llm_usage_events. All LLM calls are mocked.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel

from packages.infrastructure.llm.client import LLMCallError, LLMClient


class _Schema(BaseModel):
    value: str


def _fake_usage(prompt_tokens: int = 100, completion_tokens: int = 50) -> MagicMock:
    usage = MagicMock()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens
    usage.total_tokens = prompt_tokens + completion_tokens
    return usage


def _fake_response(
    *,
    finish_reason: str = "stop",
    refusal: str | None = None,
    content: str = '{"value": "ok"}',
    model: str = "gpt-4o-mini",
) -> MagicMock:
    message = MagicMock()
    message.content = content
    message.refusal = refusal

    choice = MagicMock()
    choice.finish_reason = finish_reason
    choice.message = message

    response = MagicMock()
    response.choices = [choice]
    response.usage = _fake_usage()
    response.model = model
    return response


def _client_with_mocked_openai(response: MagicMock) -> LLMClient:
    client = LLMClient(model="gpt-4o-mini")
    client._api_key = "test-key"
    fake_openai_client = MagicMock()
    fake_openai_client.chat.completions.create.return_value = response
    client._get_client = MagicMock(return_value=fake_openai_client)
    return client


class TestCompleteStructuredEmitsUsageBeforeRaising:
    def test_success_path_emits_usage_once(self):
        client = _client_with_mocked_openai(_fake_response())
        with patch("packages.infrastructure.llm.usage_writer.persist_usage") as mock_persist:
            result = client.complete_structured("sys", "user", _Schema)
        assert result.value == "ok"
        mock_persist.assert_called_once()
        _, kwargs = mock_persist.call_args
        assert kwargs["prompt_tokens"] == 100
        assert kwargs["completion_tokens"] == 50

    def test_finish_reason_length_still_emits_usage(self):
        client = _client_with_mocked_openai(_fake_response(finish_reason="length"))
        with patch("packages.infrastructure.llm.usage_writer.persist_usage") as mock_persist:
            with pytest.raises(LLMCallError, match="truncated"):
                client.complete_structured("sys", "user", _Schema)
        mock_persist.assert_called_once()
        _, kwargs = mock_persist.call_args
        assert kwargs["prompt_tokens"] == 100
        assert kwargs["completion_tokens"] == 50

    def test_content_filter_still_emits_usage(self):
        client = _client_with_mocked_openai(_fake_response(finish_reason="content_filter"))
        with patch("packages.infrastructure.llm.usage_writer.persist_usage") as mock_persist:
            with pytest.raises(LLMCallError, match="content filter"):
                client.complete_structured("sys", "user", _Schema)
        mock_persist.assert_called_once()

    def test_refusal_still_emits_usage(self):
        client = _client_with_mocked_openai(_fake_response(refusal="cannot help with that"))
        with patch("packages.infrastructure.llm.usage_writer.persist_usage") as mock_persist:
            with pytest.raises(LLMCallError, match="refused"):
                client.complete_structured("sys", "user", _Schema)
        mock_persist.assert_called_once()

    def test_unparseable_json_still_emits_usage(self):
        client = _client_with_mocked_openai(_fake_response(content="not json at all"))
        with patch("packages.infrastructure.llm.usage_writer.persist_usage") as mock_persist:
            with pytest.raises(LLMCallError, match="unparseable"):
                client.complete_structured("sys", "user", _Schema)
        mock_persist.assert_called_once()

    def test_trailing_duplicate_json_recovers_and_emits_usage_once(self):
        """Known recoverable case (see client.py comment) — must not double-emit."""
        duplicated = '{"value": "ok"}{"value": "ok"}'
        client = _client_with_mocked_openai(_fake_response(content=duplicated))
        with patch("packages.infrastructure.llm.usage_writer.persist_usage") as mock_persist:
            result = client.complete_structured("sys", "user", _Schema)
        assert result.value == "ok"
        mock_persist.assert_called_once()

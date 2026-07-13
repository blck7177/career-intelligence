"""
Tests for OpenClawHttpRuntime — the HTTP-based agent runtime.

Regression coverage for a 2026-07-12 accounting-gap audit: a 200 OK response
means the underlying LLM call was already billed, so a malformed/unexpected
usage payload shape must not raise past invoke() and discard the whole
(already-paid-for) result. Also covers cache/reasoning token extraction and
the standard timeout/error/non-200/invalid-JSON paths.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from packages.contracts.agents.invocation import AgentInvocationSpec
from packages.infrastructure.agent_runtime.openclaw_http import OpenClawHttpRuntime


def _make_spec(tmp_path: Path) -> AgentInvocationSpec:
    return AgentInvocationSpec(
        invocation_id="ainv_http_test",
        run_id="run_001",
        task_id="task_001",
        workspace_id="ws_001",
        agent_id="career-search-agent",
        skill_contract_version="career-search-v1",
        session_key="agent:career-search-agent:workspace:ws_001:run:run_001:task:task_001:attempt:1",
        input_spec_path=str(tmp_path / "input.json"),
        output_manifest_path=str(tmp_path / "output_manifest.json"),
        created_at=datetime.now(timezone.utc),
        timeout_seconds=60,
    )


def _make_runtime(tmp_path: Path) -> OpenClawHttpRuntime:
    config_path = tmp_path / "openclaw.json"
    config_path.write_text(json.dumps({
        "gateway": {"auth": {"token": "test-token"}},
        "agents": {"defaults": {"model": {"primary": "openai/gpt-5.4-mini"}}},
    }))
    return OpenClawHttpRuntime(config_path=str(config_path))


class _FakeResponse:
    def __init__(self, status_code: int, body) -> None:
        self.status_code = status_code
        self._body = body
        self.text = body if isinstance(body, str) else json.dumps(body)

    def json(self):
        if isinstance(self._body, str):
            raise ValueError("not json")
        return self._body


class TestExtractUsageIsDefensive:
    def test_non_dict_payload_does_not_raise(self, tmp_path):
        runtime = _make_runtime(tmp_path)
        assert runtime._extract_usage(["not", "a", "dict"]) is None
        assert runtime._extract_usage("also not a dict") is None
        assert runtime._extract_usage(None) is None

    def test_non_dict_usage_field_does_not_raise(self, tmp_path):
        runtime = _make_runtime(tmp_path)
        assert runtime._extract_usage({"usage": "not a dict"}) is None

    def test_malformed_token_detail_subfields_do_not_raise(self, tmp_path):
        """prompt_tokens_details / completion_tokens_details present but not dicts."""
        runtime = _make_runtime(tmp_path)
        usage = runtime._extract_usage({
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "prompt_tokens_details": ["unexpected", "list"],
                "completion_tokens_details": "unexpected string",
            }
        })
        assert usage is not None
        assert usage.input_tokens == 100
        assert usage.output_tokens == 50
        assert usage.cache_read_tokens == 0
        assert usage.reasoning_tokens == 0

    def test_normal_payload_extracts_cache_and_reasoning(self, tmp_path):
        runtime = _make_runtime(tmp_path)
        usage = runtime._extract_usage({
            "usage": {
                "prompt_tokens": 1002430,
                "completion_tokens": 8175,
                "prompt_tokens_details": {"cached_tokens": 955392},
                "completion_tokens_details": {"reasoning_tokens": 4966},
            }
        })
        assert usage is not None
        assert usage.input_tokens == 1002430
        assert usage.cache_read_tokens == 955392
        assert usage.reasoning_tokens == 4966

    def test_zero_zero_returns_none(self, tmp_path):
        runtime = _make_runtime(tmp_path)
        assert runtime._extract_usage({"usage": {"prompt_tokens": 0, "completion_tokens": 0}}) is None


class TestInvokeSurvivesMalformedSuccessResponse:
    def test_extract_usage_exception_does_not_lose_successful_response(self, monkeypatch, tmp_path):
        """A 200 OK means the call was already billed — extraction errors must
        not propagate and discard the content/exit_code along with the usage."""
        runtime = _make_runtime(tmp_path)

        def fake_post(url, headers, json, timeout):
            return _FakeResponse(200, {"choices": [{"message": {"content": "hi"}}], "usage": "corrupt"})

        monkeypatch.setattr(httpx, "post", fake_post)
        monkeypatch.setattr(
            runtime, "_extract_usage", lambda payload: (_ for _ in ()).throw(RuntimeError("boom"))
        )

        result = runtime.invoke(_make_spec(tmp_path))

        assert result.exit_code == 0
        assert result.usage is None
        assert "hi" in result.stdout

    def test_normal_success_path_returns_usage(self, monkeypatch, tmp_path):
        runtime = _make_runtime(tmp_path)

        def fake_post(url, headers, json, timeout):
            return _FakeResponse(200, {
                "choices": [{"message": {"content": "done"}}],
                "usage": {"prompt_tokens": 500, "completion_tokens": 100},
            })

        monkeypatch.setattr(httpx, "post", fake_post)
        result = runtime.invoke(_make_spec(tmp_path))

        assert result.exit_code == 0
        assert result.usage is not None
        assert result.usage.input_tokens == 500
        assert result.usage.model == "gpt-5.4-mini"


class TestInvokeFailureBranchesReturnNoUsage:
    """Documents the known, currently-unrecoverable gap: on these paths there
    is no way to reconstruct usage without an upstream OpenClaw gateway
    change (the /v1/chat/completions response carries no session identifier
    in body or headers — verified against openclaw-source's openai-http.ts)."""

    def test_timeout_returns_no_usage(self, monkeypatch, tmp_path):
        runtime = _make_runtime(tmp_path)

        def fake_post(url, headers, json, timeout):
            raise httpx.TimeoutException("timed out")

        monkeypatch.setattr(httpx, "post", fake_post)
        result = runtime.invoke(_make_spec(tmp_path))

        assert result.timed_out is True
        assert result.usage is None

    def test_transport_error_returns_no_usage(self, monkeypatch, tmp_path):
        runtime = _make_runtime(tmp_path)

        def fake_post(url, headers, json, timeout):
            raise httpx.ConnectError("connection reset")

        monkeypatch.setattr(httpx, "post", fake_post)
        result = runtime.invoke(_make_spec(tmp_path))

        assert result.exit_code == 1
        assert result.usage is None

    def test_non_200_returns_no_usage(self, monkeypatch, tmp_path):
        runtime = _make_runtime(tmp_path)

        def fake_post(url, headers, json, timeout):
            return _FakeResponse(500, {"error": "internal"})

        monkeypatch.setattr(httpx, "post", fake_post)
        result = runtime.invoke(_make_spec(tmp_path))

        assert result.exit_code == 1
        assert result.usage is None

    def test_invalid_json_body_returns_no_usage(self, monkeypatch, tmp_path):
        runtime = _make_runtime(tmp_path)

        def fake_post(url, headers, json, timeout):
            return _FakeResponse(200, "not valid json{{{")

        monkeypatch.setattr(httpx, "post", fake_post)
        result = runtime.invoke(_make_spec(tmp_path))

        assert result.exit_code == 1
        assert result.usage is None

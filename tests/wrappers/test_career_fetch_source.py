"""
Tests for career_fetch_source's agent-visible truncation behavior.

When a posting is resolved via the ATS's structured API (jd_fetch.service's
_fetch_via_ats_api), realness is already guaranteed by that API's contract —
the agent doesn't need the full page text to re-verify it, only enough to
judge relevance/seniority. Scraped (non-ATS-API) fetches keep the full
excerpt because the agent's realness check *is* reading that text.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

# Wrapper lives outside packages/; import by path.
_WRAPPER_DIR = Path(__file__).resolve().parents[2] / "tools" / "wrappers" / "agent_tools"
sys.path.insert(0, str(_WRAPPER_DIR))

import career_fetch_source  # noqa: E402
from career_fetch_source import main  # noqa: E402


def _run(tmp_path: Path, spec: dict) -> dict:
    task_spec_path = tmp_path / "task_spec.json"
    output_path = tmp_path / "output.json"
    task_spec_path.write_text(json.dumps(spec))

    runner = CliRunner()
    with patch.object(career_fetch_source, "DomainRateLimiter") as mock_limiter_cls:
        mock_limiter_cls.return_value.wait_and_acquire = MagicMock()
        result = runner.invoke(
            main,
            ["--task-spec", str(task_spec_path), "--output", str(output_path)],
        )

    assert result.exit_code == 0, result.output
    return json.loads(output_path.read_text())


def _fetch_result(*, source: str, jd_text: str):
    mock = MagicMock()
    mock.ok = True
    mock.jd_text = jd_text
    mock.jd_hash = "abc123"
    mock.error = None
    mock.source = source
    mock.fetch_status = "success"
    return mock


class TestAgentVisibleTruncation:
    def test_ats_api_source_returns_short_excerpt_with_note(self, tmp_path: Path):
        full_text = "Real posting text. " * 1000  # >> 1500 chars, << 50000-char save cap
        spec = {
            "url": "https://boards.greenhouse.io/acme/jobs/123",
            "source_type": "greenhouse",
            "run_id": "run_1",
            "task_id": "task_1",
            "artifacts_dir": str(tmp_path / "artifacts"),
        }

        with patch.object(
            career_fetch_source,
            "fetch_jd_from_url",
            return_value=_fetch_result(source="ats_api", jd_text=full_text),
        ):
            output = _run(tmp_path, spec)

        assert output["content_length"] == len(full_text)
        assert len(output["text"]) == career_fetch_source._AGENT_VISIBLE_CHARS_ATS_API
        assert "note" in output
        assert "structured API" in output["note"]

        # Full text is still persisted for downstream (job_report/fit_report) use.
        saved = Path(output["jd_text_path"]).read_text()
        assert saved == full_text.strip()

    def test_scraped_source_keeps_full_excerpt_no_note(self, tmp_path: Path):
        full_text = "Scraped page text. " * 5000
        spec = {
            "url": "https://acme.com/careers/job/1",
            "source_type": "html_fallback",
            "run_id": "run_2",
            "task_id": "task_2",
            "artifacts_dir": str(tmp_path / "artifacts"),
        }

        with patch.object(
            career_fetch_source,
            "fetch_jd_from_url",
            return_value=_fetch_result(source="worker_fetch", jd_text=full_text),
        ):
            output = _run(tmp_path, spec)

        assert output["content_length"] == len(full_text)
        assert len(output["text"]) == min(len(full_text), career_fetch_source._AGENT_VISIBLE_CHARS_SCRAPED)
        assert "note" not in output

    def test_trace_event_records_jd_source(self, tmp_path: Path):
        full_text = "Real posting text. " * 100
        spec = {
            "url": "https://boards.greenhouse.io/acme/jobs/123",
            "source_type": "greenhouse",
            "run_id": "run_3",
            "task_id": "task_3",
            "artifacts_dir": str(tmp_path / "artifacts"),
        }

        with patch.object(
            career_fetch_source,
            "fetch_jd_from_url",
            return_value=_fetch_result(source="ats_api", jd_text=full_text),
        ):
            _run(tmp_path, spec)

        trace_path = tmp_path / "artifacts" / "run_3" / "task_3" / "trace_events.jsonl"
        entry = json.loads(trace_path.read_text().strip())
        assert entry["jd_source"] == "ats_api"

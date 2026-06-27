"""
Unit tests for JD fetch service and discovery job persistence.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from packages.contracts.agents.manifests import DiscoveryManifest
from packages.infrastructure.jd_fetch.service import (
    MIN_JD_TEXT_LEN,
    compute_jd_hash,
    compute_url_hash,
    fetch_jd_from_url,
    resolve_jd,
    save_fetched_jd_artifact,
    strip_html,
)


SAMPLE_HTML = f"""
<html><head><title>Job</title></head><body>
<h1>Market Risk Analyst</h1>
<p>{'We need a strong candidate. ' * 30}</p>
</body></html>
"""


class TestStripHtml:
    def test_removes_tags(self):
        text = strip_html(SAMPLE_HTML)
        assert "<html>" not in text
        assert "Market Risk Analyst" in text
        assert len(text) >= MIN_JD_TEXT_LEN


class TestComputeHashes:
    def test_url_hash_stable(self):
        assert compute_url_hash("https://example.com/job/1") == compute_url_hash(
            "https://example.com/job/1"
        )

    def test_jd_hash_is_16_chars(self):
        h = compute_jd_hash("hello world")
        assert len(h) == 16


class TestFetchJdFromUrl:
    def test_success_html(self):
        response = httpx.Response(200, text=SAMPLE_HTML, request=httpx.Request("GET", "https://x.com"))
        with patch("packages.infrastructure.jd_fetch.service.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = response
            result = fetch_jd_from_url("https://example.com/job/1")

        assert result.ok is True
        assert result.jd_text is not None
        assert result.jd_hash == compute_jd_hash(result.jd_text)
        assert result.source == "worker_fetch"

    def test_http_404(self):
        request = httpx.Request("GET", "https://example.com/missing")
        response = httpx.Response(404, request=request)
        with patch("packages.infrastructure.jd_fetch.service.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.side_effect = httpx.HTTPStatusError(
                "404", request=request, response=response
            )
            result = fetch_jd_from_url("https://example.com/missing")

        assert result.ok is False
        assert "404" in (result.error or "")

    def test_too_short_content(self):
        response = httpx.Response(200, text="<html><body>hi</body></html>", request=httpx.Request("GET", "https://x.com"))
        with patch("packages.infrastructure.jd_fetch.service.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = response
            result = fetch_jd_from_url("https://example.com/short")

        assert result.ok is False
        assert result.fetch_status == "too_short"


class TestArtifactCache:
    def test_save_and_resolve_from_artifact(self, tmp_path: Path):
        url = "https://boards.greenhouse.io/acme/jobs/123"
        jd_text = "Senior Engineer role. " + ("Details here. " * 40)
        save_fetched_jd_artifact(
            artifact_dir=tmp_path,
            url=url,
            raw_content=jd_text,
            content_type="text/plain",
        )

        with patch("packages.infrastructure.jd_fetch.service.fetch_jd_from_url") as mock_fetch:
            result = resolve_jd(url, "greenhouse", tmp_path)

        mock_fetch.assert_not_called()
        assert result.ok is True
        assert result.source == "artifact"

    def test_resolve_falls_back_to_fetch_when_no_artifact(self, tmp_path: Path):
        url = "https://example.com/job/2"
        with patch("packages.infrastructure.jd_fetch.service.fetch_jd_from_url") as mock_fetch:
            mock_fetch.return_value.ok = True
            mock_fetch.return_value.jd_text = "x" * MIN_JD_TEXT_LEN
            mock_fetch.return_value.jd_hash = compute_jd_hash("x" * MIN_JD_TEXT_LEN)
            mock_fetch.return_value.error = None
            mock_fetch.return_value.fetch_status = "success"
            mock_fetch.return_value.source = "worker_fetch"

            result = resolve_jd(url, "html_fallback", tmp_path)

        mock_fetch.assert_called_once_with(url)
        assert result.ok is True
        assert result.source == "worker_fetch"


def _make_manifest(pool_path: Path, count: int = 1) -> DiscoveryManifest:
    return DiscoveryManifest(
        invocation_id="ainv_test",
        status="completed",
        stop_reason="done",
        candidate_count=count,
        sources_tried=["greenhouse"],
        artifact_paths={"candidate_pool": str(pool_path)},
    )


class TestPersistDiscoveredJobs:
    def test_reportable_on_successful_fetch(self, tmp_path: Path):
        pool = tmp_path / "candidate_pool.jsonl"
        url = "https://example.com/job/new"
        pool.write_text(
            json.dumps(
                {
                    "url": url,
                    "title": "Analyst",
                    "company": "Acme",
                    "source_type": "greenhouse",
                }
            )
            + "\n"
        )
        manifest = _make_manifest(pool)

        mock_job = MagicMock()
        mock_job.id = "job-001"
        mock_job_repo = MagicMock()
        mock_job_repo.get_by_canonical_url.return_value = None
        mock_job_repo.create.return_value = mock_job

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        ok_result = MagicMock()
        ok_result.ok = True
        ok_result.jd_text = "Role description. " * 30
        ok_result.jd_hash = compute_jd_hash(ok_result.jd_text)
        ok_result.error = None
        ok_result.source = "worker_fetch"
        ok_result.fetch_status = "success"

        with patch("apps.worker.tasks.search_run.get_session", return_value=mock_session), patch(
            "apps.worker.tasks.search_run.JobRepository", return_value=mock_job_repo
        ), patch("apps.worker.tasks.search_run.resolve_jd", return_value=ok_result):
            from apps.worker.tasks.search_run import _persist_discovered_jobs

            stats = _persist_discovered_jobs(manifest, "run_1", "task_1")

        assert stats["jobs_ingested"] == 1
        assert stats["jobs_reportable"] == 1
        assert stats["jobs_fetch_failed"] == 0
        _, kwargs = mock_job_repo.create.call_args
        assert kwargs["status"] == "reportable"
        assert kwargs["jd_text"] == ok_result.jd_text

    def test_discovered_with_fetch_error_on_failure(self, tmp_path: Path):
        pool = tmp_path / "candidate_pool.jsonl"
        url = "https://example.com/job/fail"
        pool.write_text(
            json.dumps(
                {
                    "url": url,
                    "title": "Analyst",
                    "company": "Acme",
                    "source_type": "greenhouse",
                }
            )
            + "\n"
        )
        manifest = _make_manifest(pool)

        mock_job = MagicMock()
        mock_job.id = "job-002"
        mock_job_repo = MagicMock()
        mock_job_repo.get_by_canonical_url.return_value = None
        mock_job_repo.create.return_value = mock_job

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        fail_result = MagicMock()
        fail_result.ok = False
        fail_result.jd_text = None
        fail_result.jd_hash = None
        fail_result.error = "HTTP 404 fetching url"
        fail_result.source = "worker_fetch"
        fail_result.fetch_status = "failed"

        with patch("apps.worker.tasks.search_run.get_session", return_value=mock_session), patch(
            "apps.worker.tasks.search_run.JobRepository", return_value=mock_job_repo
        ), patch("apps.worker.tasks.search_run.resolve_jd", return_value=fail_result):
            from apps.worker.tasks.search_run import _persist_discovered_jobs

            stats = _persist_discovered_jobs(manifest, "run_1", "task_1")

        assert stats["jobs_fetch_failed"] == 1
        assert stats["jobs_reportable"] == 0
        _, kwargs = mock_job_repo.create.call_args
        assert kwargs["status"] == "discovered"
        assert kwargs["raw_payload_json"]["fetch_error"] == "HTTP 404 fetching url"

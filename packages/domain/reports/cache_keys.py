"""
Cache key builders for job reports and fit reports.

Pure functions — no IO, no DB, no LLM.
"""
from __future__ import annotations


def job_report_cache_key(
    job_id: str,
    jd_hash: str,
    prompt_version: str,
    research_bundle_hash: str,
) -> str:
    """
    Stable string key for a job report.
    A change in any dimension produces a distinct key → cache miss → re-generation.
    """
    return f"job_report::{job_id}::{jd_hash}::{prompt_version}::{research_bundle_hash}"


def fit_report_cache_key(
    workspace_id: str,
    job_report_id: str,
    profile_hash: str,
    prompt_version: str,
) -> str:
    """
    Stable string key for a fit report.
    Scoped by workspace (fit reports are workspace-private).
    """
    return f"fit_report::{workspace_id}::{job_report_id}::{profile_hash}::{prompt_version}"

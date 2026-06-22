"""
Shared fixtures for report service tests.

Strategy: SQLite in-memory with real SQLAlchemy ORM, mocked LLM calls.
- DB layer (repositories, cache checks, row writes) runs against real SQLite.
- LLM calls (generate_fit_report, analyze_role) are patched per-test.
- Artifact file writes use pytest tmp_path.
"""
from __future__ import annotations

import hashlib

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from packages.infrastructure.db.models import Base, Job, JobReport, Workspace

# Pre-compute the jd_hash that the service will derive so cache keys align.
_SEED_JD_TEXT = "We need a risk analyst with 5+ years of VaR and stress testing experience."
SEED_JD_HASH = hashlib.md5(_SEED_JD_TEXT.encode()).hexdigest()[:16]


@pytest.fixture()
def db_session():
    """In-memory SQLite session; rolled back after each test."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    # SQLite does not enforce FK constraints by default — enable for realism.
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(conn, _):
        conn.execute("PRAGMA foreign_keys = OFF")  # OFF so we can seed in any order

    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture()
def seeded_db(db_session: Session) -> dict:
    """
    Seed workspace + reportable job + active job_report.
    Returns a dict of IDs for use in tests.
    """
    ws = Workspace(id="ws_seed", name="Test Workspace")
    db_session.add(ws)

    job = Job(
        id="job_seed",
        canonical_url="https://example.com/jobs/risk-analyst",
        source_url="https://example.com/jobs/risk-analyst",
        source_type="ats",
        title="Risk Analyst",
        company="Example Bank",
        jd_text=_SEED_JD_TEXT,
        jd_hash=SEED_JD_HASH,
        status="reportable",
    )
    db_session.add(job)

    job_report = JobReport(
        id="rpt_seed",
        job_id="job_seed",
        jd_hash=SEED_JD_HASH,
        prompt_version="0.2.0",
        analysis_version="1.0",
        used_research=False,
        research_bundle_hash="none",
        status="active",
        structured_json={
            "primary_workstream": "market_risk",
            "business_context": {"summary": "Risk management role"},
        },
        summary_json={"primary_workstream": "market_risk"},
    )
    db_session.add(job_report)
    db_session.flush()

    return {
        "workspace_id": "ws_seed",
        "job_id": "job_seed",
        "job_report_id": "rpt_seed",
    }


SAMPLE_PROFILE = {
    # Stable id so cache key (candidate_profile_id) is consistent across calls.
    "id": "cand_sample_stable",
    "years_experience": 5,
    "current_background": "Risk analyst at mid-size bank",
    "domain_experience": ["market risk", "credit risk"],
    "technical_skills": ["Python", "SQL"],
    "analytical_methods": ["VaR", "stress testing"],
    "finance_domains": ["fixed income", "derivatives"],
    "tools": ["Bloomberg", "Excel"],
    "representative_projects": [
        {
            "title": "VaR Model Rebuild",
            "description": "Rebuilt the historical VaR model from scratch.",
            "skills_used": ["Python", "statistics"],
            "quantified_impact": "Reduced model run time by 40%",
        }
    ],
}

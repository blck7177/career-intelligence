"""
Career Intelligence Dev Console — local-only LLM cost monitoring dashboard.

Read-only: queries Postgres directly, does not modify any data.
No authentication: local development use only.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine, text

_REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_REPO_ROOT / ".env")

_DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://career:career@localhost:5432/career_openclaw"
)
_engine = create_engine(_DATABASE_URL, pool_pre_ping=True, pool_size=2)

app = FastAPI(title="Career Intelligence Dev Console", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/dashboard/cost-summary")
def cost_summary():
    with _engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT
                r.run_type,
                count(u.id)                     AS llm_calls,
                coalesce(sum(u.prompt_tokens), 0)     AS prompt_tokens,
                coalesce(sum(u.completion_tokens), 0)  AS completion_tokens,
                coalesce(sum(u.total_tokens), 0)       AS total_tokens,
                coalesce(sum(u.estimated_cost_usd), 0) AS estimated_cost_usd
            FROM llm_usage_events u
            JOIN runs r ON u.run_id = r.id
            GROUP BY r.run_type
            ORDER BY sum(u.estimated_cost_usd) DESC
        """)).fetchall()
    return [
        {
            "run_type": r.run_type,
            "llm_calls": r.llm_calls,
            "prompt_tokens": r.prompt_tokens,
            "completion_tokens": r.completion_tokens,
            "total_tokens": r.total_tokens,
            "estimated_cost_usd": round(float(r.estimated_cost_usd), 6),
        }
        for r in rows
    ]


@app.get("/api/dashboard/recent-runs")
def recent_runs(limit: int = Query(50, ge=1, le=200)):
    with _engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT
                    r.id,
                    r.run_type,
                    r.status,
                    r.error_code,
                    r.created_at,
                    coalesce(sum(u.prompt_tokens), 0)     AS prompt_tokens,
                    coalesce(sum(u.completion_tokens), 0)  AS completion_tokens,
                    coalesce(sum(u.total_tokens), 0)       AS total_tokens,
                    coalesce(sum(u.estimated_cost_usd), 0) AS estimated_cost_usd,
                    count(u.id)                            AS llm_calls
                FROM runs r
                LEFT JOIN llm_usage_events u ON u.run_id = r.id
                GROUP BY r.id, r.run_type, r.status, r.error_code, r.created_at
                ORDER BY r.created_at DESC
                LIMIT :limit
            """),
            {"limit": limit},
        ).fetchall()
    return [
        {
            "id": r.id,
            "run_type": r.run_type,
            "status": r.status,
            "error_code": r.error_code,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "prompt_tokens": r.prompt_tokens,
            "completion_tokens": r.completion_tokens,
            "total_tokens": r.total_tokens,
            "estimated_cost_usd": round(float(r.estimated_cost_usd), 6),
            "llm_calls": r.llm_calls,
        }
        for r in rows
    ]


@app.get("/api/dashboard/runs/{run_id}/usage")
def run_usage(run_id: str):
    with _engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT id, call_site, model, prompt_tokens, completion_tokens,
                       total_tokens, estimated_cost_usd, created_at
                FROM llm_usage_events
                WHERE run_id = :run_id
                ORDER BY created_at
            """),
            {"run_id": run_id},
        ).fetchall()
    return [
        {
            "id": r.id,
            "call_site": r.call_site,
            "model": r.model,
            "prompt_tokens": r.prompt_tokens,
            "completion_tokens": r.completion_tokens,
            "total_tokens": r.total_tokens,
            "estimated_cost_usd": round(float(r.estimated_cost_usd), 6)
            if r.estimated_cost_usd
            else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Static frontend serving
# ---------------------------------------------------------------------------

_DIST = Path(__file__).parent.parent / "web" / "dist"

if _DIST.exists():
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def serve_frontend(full_path: str):
        return FileResponse(_DIST / "index.html")

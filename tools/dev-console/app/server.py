"""
Career Intelligence Dev Console — LLM cost monitoring dashboard.

Read-only: queries Postgres directly, does not modify any data.

Security:
  - Set CONSOLE_TOKEN to require Bearer token or ?token= authentication.
  - When CONSOLE_TOKEN is unset, all requests are allowed (local dev mode).
  - Set CONSOLE_CORS_ORIGINS (comma-separated) to restrict allowed origins.
"""

from __future__ import annotations

import hmac
import logging
import os
import subprocess
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_REPO_ROOT / ".env")


def _resolve_database_url() -> str:
    url = os.environ.get(
        "DATABASE_URL", "postgresql://career:career@localhost:5432/career_openclaw"
    )
    # When postgres runs inside Docker without host port mapping, try to
    # discover the container IP automatically.
    try:
        engine = create_engine(url, pool_pre_ping=True, pool_size=1)
        with engine.connect():
            pass
        engine.dispose()
        return url
    except Exception:
        pass

    try:
        ip = subprocess.check_output(
            ["docker", "inspect", "compose-postgres-1",
             "--format", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}"],
            text=True, timeout=5,
        ).strip()
        if ip:
            docker_url = url.replace("@localhost:", f"@{ip}:").replace(
                "@127.0.0.1:", f"@{ip}:"
            )
            logger.info("Using Docker postgres at %s", ip)
            return docker_url
    except Exception:
        pass

    return url


_DATABASE_URL = _resolve_database_url()
_engine = create_engine(_DATABASE_URL, pool_pre_ping=True, pool_size=2)

_CONSOLE_TOKEN = os.environ.get("CONSOLE_TOKEN", "")
_CORS_ORIGINS = [
    o.strip()
    for o in os.environ.get("CONSOLE_CORS_ORIGINS", "").split(",")
    if o.strip()
]

app = FastAPI(title="Career Intelligence Dev Console", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS or ["*"],
    allow_methods=["GET"],
    allow_headers=["Authorization"],
)


@app.middleware("http")
async def _auth_middleware(request: Request, call_next):
    if not _CONSOLE_TOKEN:
        return await call_next(request)

    # Static assets and the SPA shell don't need auth — the frontend JS
    # reads the token from the URL and shows an auth-wall if needed.
    if request.url.path.startswith("/assets") or not request.url.path.startswith("/api"):
        return await call_next(request)

    token = None
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:]
    if not token:
        token = request.query_params.get("token")

    if not token or not hmac.compare_digest(token, _CONSOLE_TOKEN):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)

    return await call_next(request)


def _build_filters(
    workspace_col: str,
    time_col: str,
    workspace_id: str | None,
    since: str | None,
    until: str | None,
    *,
    prefix: str = "WHERE",
) -> tuple[str, dict]:
    clauses: list[str] = []
    params: dict = {}
    if workspace_id:
        clauses.append(f"{workspace_col} = :workspace_id")
        params["workspace_id"] = workspace_id
    if since:
        clauses.append(f"{time_col} >= :since")
        params["since"] = since
    if until:
        clauses.append(f"{time_col} < :until")
        params["until"] = until
    sql = (f" {prefix} " + " AND ".join(clauses)) if clauses else ""
    return sql, params


@app.get("/api/dashboard/workspaces")
def workspaces():
    with _engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, name FROM workspaces ORDER BY name")
        ).fetchall()
    return [{"id": r.id, "name": r.name} for r in rows]


@app.get("/api/dashboard/cost-summary")
def cost_summary(
    workspace_id: str | None = Query(None),
    since: str | None = Query(None),
    until: str | None = Query(None),
):
    where, params = _build_filters(
        "r.workspace_id", "u.created_at", workspace_id, since, until,
    )
    with _engine.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT
                r.run_type,
                count(u.id)                     AS llm_calls,
                coalesce(sum(u.prompt_tokens), 0)     AS prompt_tokens,
                coalesce(sum(u.completion_tokens), 0)  AS completion_tokens,
                coalesce(sum(u.total_tokens), 0)       AS total_tokens,
                coalesce(sum(u.estimated_cost_usd), 0) AS estimated_cost_usd
            FROM llm_usage_events u
            JOIN runs r ON u.run_id = r.id
            {where}
            GROUP BY r.run_type
            ORDER BY sum(u.estimated_cost_usd) DESC
        """), params).fetchall()
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
def recent_runs(
    limit: int = Query(50, ge=1, le=200),
    workspace_id: str | None = Query(None),
    since: str | None = Query(None),
    until: str | None = Query(None),
):
    where, params = _build_filters(
        "r.workspace_id", "r.created_at", workspace_id, since, until,
    )
    params["limit"] = limit
    with _engine.connect() as conn:
        rows = conn.execute(
            text(f"""
                SELECT
                    r.id,
                    r.run_type,
                    r.status,
                    r.error_code,
                    r.error_message,
                    r.created_at,
                    coalesce(sum(u.prompt_tokens), 0)     AS prompt_tokens,
                    coalesce(sum(u.completion_tokens), 0)  AS completion_tokens,
                    coalesce(sum(u.total_tokens), 0)       AS total_tokens,
                    coalesce(sum(u.estimated_cost_usd), 0) AS estimated_cost_usd,
                    count(u.id)                            AS llm_calls
                FROM runs r
                LEFT JOIN llm_usage_events u ON u.run_id = r.id
                {where}
                GROUP BY r.id, r.run_type, r.status, r.error_code,
                         r.error_message, r.created_at
                ORDER BY r.created_at DESC
                LIMIT :limit
            """),
            params,
        ).fetchall()
    return [
        {
            "id": r.id,
            "run_type": r.run_type,
            "status": r.status,
            "error_code": r.error_code,
            "error_message": r.error_message,
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
def run_usage(
    run_id: str,
    workspace_id: str | None = Query(None),
    since: str | None = Query(None),
    until: str | None = Query(None),
):
    extra_where, params = _build_filters(
        "workspace_id", "created_at", workspace_id, since, until,
        prefix="AND",
    )
    params["run_id"] = run_id
    with _engine.connect() as conn:
        rows = conn.execute(
            text(f"""
                SELECT id, call_site, model, prompt_tokens, completion_tokens,
                       total_tokens, estimated_cost_usd, created_at
                FROM llm_usage_events
                WHERE run_id = :run_id
                {extra_where}
                ORDER BY created_at
            """),
            params,
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


@app.get("/api/dashboard/runs/{run_id}/errors")
def run_errors(run_id: str):
    with _engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT
                    t.id         AS task_id,
                    t.task_type,
                    t.status     AS task_status,
                    t.error_code AS task_error_code,
                    t.error_message AS task_error_message,
                    t.attempt_count,
                    ai.id        AS invocation_id,
                    ai.agent_id,
                    ai.exit_code,
                    ai.error_code   AS agent_error_code,
                    ai.error_message AS agent_error_message,
                    ai.status    AS agent_status
                FROM tasks t
                LEFT JOIN agent_invocations ai ON ai.task_id = t.id
                WHERE t.run_id = :run_id
                  AND (
                    t.status IN ('failed', 'needs_review')
                    OR (ai.exit_code IS NOT NULL AND ai.exit_code != 0)
                  )
                ORDER BY t.created_at
            """),
            {"run_id": run_id},
        ).fetchall()
    return [
        {
            "task_id": r.task_id,
            "task_type": r.task_type,
            "task_status": r.task_status,
            "task_error_code": r.task_error_code,
            "task_error_message": r.task_error_message,
            "attempt_count": r.attempt_count,
            "invocation_id": r.invocation_id,
            "agent_id": r.agent_id,
            "exit_code": r.exit_code,
            "agent_error_code": r.agent_error_code,
            "agent_error_message": r.agent_error_message,
            "agent_status": r.agent_status,
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

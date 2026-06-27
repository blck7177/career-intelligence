"""
FastAPI application entry point.

Rules (from AGENTS.md):
  - API does not call OpenClaw
  - API does not execute long tasks (only enqueue)
  - API exposes run/task/event/artifact endpoints only
  - OpenClaw internals (session_key, skill_path, stdout) are not in response DTOs
"""

from __future__ import annotations

import os
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from apps.api.routes.admin_cost import router as admin_cost_router
from apps.api.routes.admin_runs import router as admin_runs_router
from apps.api.routes.admin_users import router as admin_users_router
from apps.api.routes.health import router as health_router
from apps.api.routes.jobs import router as jobs_router
from apps.api.routes.profile import router as profile_router
from apps.api.routes.reports import router as reports_router
from apps.api.routes.runs import router as runs_router
from packages.infrastructure.observability.logging import configure_logging, set_correlation_id

configure_logging()

_ENV = os.environ.get("ENV", "development")
_DEV_MODE = os.environ.get("DEV_MODE", "0") == "1"

app = FastAPI(
    title="Career OpenClaw API",
    version="0.2.0",
    docs_url="/docs" if _DEV_MODE else None,
    redoc_url="/redoc" if _DEV_MODE else None,
    openapi_url="/openapi.json" if _DEV_MODE else None,
)

# CORS — restrict in production via environment
_CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    """
    Extract or generate a correlation_id for every request.
    Propagated downstream via X-Correlation-ID header.
    Workers inherit it via the Celery task envelope.
    """
    cid = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
    set_correlation_id(cid)
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = cid
    return response


app.include_router(health_router)
app.include_router(runs_router)
app.include_router(jobs_router)
app.include_router(reports_router)
app.include_router(profile_router)
app.include_router(admin_cost_router)
app.include_router(admin_runs_router)
app.include_router(admin_users_router)


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/docs" if _DEV_MODE else "/healthz")

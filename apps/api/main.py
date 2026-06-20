"""
FastAPI application entry point.

Rules (from AGENTS.md):
  - API does not call OpenClaw
  - API does not execute long tasks (only enqueue)
  - API exposes run/task/event/artifact endpoints only
  - OpenClaw internals (session_key, skill_path, stdout) are not in response DTOs
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.routes.health import router as health_router
from apps.api.routes.runs import router as runs_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

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
_ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(runs_router)

#!/bin/bash
# API container entrypoint.
# 1. Wait for Postgres (docker compose healthcheck should handle this, but belt + suspenders)
# 2. Run Alembic migrations
# 3. Start uvicorn

set -e

echo "[start_api] Running database migrations..."
alembic upgrade head

echo "[start_api] Starting API server..."
exec uvicorn apps.api.main:app --host 0.0.0.0 --port 8000

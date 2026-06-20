#!/usr/bin/env bash
# Start the full dev stack in tmux panes.
#
# Usage: ./scripts/dev_up.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "=== Career OpenClaw Dev Stack ==="
echo "Starting: postgres, redis, api, worker, web"
echo ""

# Check for docker compose
if command -v docker &>/dev/null && docker compose version &>/dev/null 2>&1; then
    echo "Starting infrastructure (postgres + redis) via Docker..."
    docker compose -f "$REPO_ROOT/infra/compose/docker-compose.dev.yml" \
        up postgres redis openclaw-gateway -d
    echo "Waiting for services..."
    sleep 5
else
    echo "WARNING: Docker not found. Start postgres and redis manually."
fi

# Start in tmux if available
if command -v tmux &>/dev/null && [ -n "${TMUX:-}" ]; then
    tmux new-window -n "api" "cd $REPO_ROOT && uvicorn apps.api.main:app --reload --port 8000; read"
    tmux new-window -n "worker" "cd $REPO_ROOT && celery -A apps.worker.celery_app worker --loglevel=info; read"
    tmux new-window -n "web" "cd $REPO_ROOT/apps/web && npm run dev; read"
    echo "Dev stack started in tmux windows: api, worker, web"
else
    echo ""
    echo "Start these in separate terminals:"
    echo "  Terminal 1 (API):    cd $REPO_ROOT && uvicorn apps.api.main:app --reload --port 8000"
    echo "  Terminal 2 (Worker): cd $REPO_ROOT && celery -A apps.worker.celery_app worker --loglevel=info"
    echo "  Terminal 3 (Web):    cd $REPO_ROOT/apps/web && npm run dev"
fi

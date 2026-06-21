#!/usr/bin/env bash
# Start the full dev stack in tmux panes.
#
# Usage: ./scripts/dev_up.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "=== Career OpenClaw Dev Stack ==="
echo "Starting: postgres, redis, openclaw-gateway, worker-fast, worker-agent, api, web"
echo ""

# Check for docker compose
if command -v docker &>/dev/null && docker compose version &>/dev/null 2>&1; then
    echo "Starting full Docker stack (postgres, redis, openclaw-gateway, worker-fast, worker-agent)..."
    docker compose -f "$REPO_ROOT/infra/compose/docker-compose.dev.yml" \
        up postgres redis openclaw-gateway worker-fast worker-agent -d --build
    echo "Waiting for services to become healthy..."
    sleep 10
else
    echo "WARNING: Docker not found. Start postgres, redis, openclaw-gateway, and workers manually."
fi

# Start api and web locally in tmux if available
if command -v tmux &>/dev/null && [ -n "${TMUX:-}" ]; then
    tmux new-window -n "api" "cd $REPO_ROOT && uvicorn apps.api.main:app --reload --port 8000; read"
    tmux new-window -n "web" "cd $REPO_ROOT/apps/web && npm run dev; read"
    echo "Dev stack started: Docker workers running in background, tmux windows: api, web"
else
    echo ""
    echo "Docker workers (worker-fast, worker-agent) are running in the background."
    echo "Start these in separate terminals:"
    echo "  Terminal 1 (API): cd $REPO_ROOT && uvicorn apps.api.main:app --reload --port 8000"
    echo "  Terminal 2 (Web): cd $REPO_ROOT/apps/web && npm run dev"
fi

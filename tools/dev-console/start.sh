#!/usr/bin/env bash
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$DIR/../.." && pwd)"

# Setup venv if needed
if [ ! -d "$DIR/.venv" ]; then
  echo "-> Creating virtual environment..."
  python3 -m venv "$DIR/.venv"
  "$DIR/.venv/bin/pip" install -q -r "$DIR/requirements.txt"
fi

# Install frontend deps if needed
if [ ! -d "$DIR/web/node_modules" ]; then
  echo "-> Installing frontend dependencies..."
  cd "$DIR/web" && npm install --silent
fi

# Build frontend if needed
if [ ! -d "$DIR/web/dist" ] || [ "$DIR/web/src/App.tsx" -nt "$DIR/web/dist/index.html" ]; then
  echo "-> Building frontend..."
  cd "$DIR/web" && npm run build
fi

# Kill existing process on :8800
if lsof -ti :8800 &>/dev/null; then
  echo "-> Killing existing process on :8800..."
  lsof -ti :8800 | xargs kill -9 2>/dev/null || true
  sleep 0.5
fi

echo "-> Starting Career Intelligence Dev Console on http://localhost:8800"
cd "$DIR"
.venv/bin/uvicorn app.server:app --host 0.0.0.0 --port 8800 --reload

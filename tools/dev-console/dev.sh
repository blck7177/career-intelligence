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

# Kill existing processes
for port in 8800 5174; do
  if lsof -ti :$port &>/dev/null; then
    lsof -ti :$port | xargs kill -9 2>/dev/null || true
  fi
done
sleep 0.5

# Start backend
cd "$DIR"
.venv/bin/uvicorn app.server:app --host 0.0.0.0 --port 8800 --reload &
BACKEND_PID=$!

# Start frontend dev server
cd "$DIR/web"
npm run dev &
FRONTEND_PID=$!

echo ""
echo "  Backend:  http://localhost:8800"
echo "  Frontend: http://localhost:5174  (proxies /api to backend)"
echo ""

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT TERM
wait

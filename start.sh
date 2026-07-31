#!/usr/bin/env bash
# Start UAMD GPT backend + frontend
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"

echo "→ Starting backend on :5001"
cd "$ROOT/backend"
# Prefer Python 3.11 if available
if [ -f .venv/bin/activate ]; then
  source .venv/bin/activate
fi
python app.py &
BACKEND_PID=$!

echo "→ Starting frontend on :5173"
cd "$ROOT/frontend"
npm run dev &
FRONTEND_PID=$!

cleanup() {
  kill $BACKEND_PID $FRONTEND_PID 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo ""
echo "UAMD GPT is running:"
echo "  Frontend: http://localhost:5173"
echo "  Backend:  http://localhost:5001"
echo ""
wait

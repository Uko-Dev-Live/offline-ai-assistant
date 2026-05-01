#!/usr/bin/env bash
# Launch the Offline AI Assistant in development mode.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

# Load .env if present.
if [[ -f .env ]]; then
  set -a; source .env; set +a
fi

# shellcheck disable=SC1091
source .venv/bin/activate

HOST="${APP_HOST:-127.0.0.1}"
PORT="${APP_PORT:-8000}"

echo ">> Starting on http://${HOST}:${PORT}"
exec uvicorn app.main:app --host "$HOST" --port "$PORT" --log-level info

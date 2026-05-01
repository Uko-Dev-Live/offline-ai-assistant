#!/usr/bin/env bash
# One-shot installer for the Offline AI Assistant on Ubuntu.
# Idempotent — safe to re-run.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MODEL="${MODEL_NAME:-llama3.2:3b}"

echo ">> Project: $PROJECT_DIR"
echo ">> Model:   $MODEL"

# 1. System packages
echo ">> Installing system packages (sudo will be requested)..."
sudo apt-get update -y
sudo apt-get install -y python3 python3-venv python3-pip curl

# 2. Ollama
if ! command -v ollama >/dev/null 2>&1; then
  echo ">> Installing Ollama..."
  curl -fsSL https://ollama.com/install.sh | sh
else
  echo ">> Ollama already installed: $(ollama --version || true)"
fi

# 3. Make sure Ollama is up
if ! systemctl is-active --quiet ollama 2>/dev/null; then
  echo ">> Starting Ollama service..."
  sudo systemctl enable --now ollama || ollama serve >/dev/null 2>&1 &
  sleep 2
fi

# 4. Pull the model
echo ">> Pulling model: $MODEL  (this can take a while on first run)"
ollama pull "$MODEL"

# 5. Python virtualenv
cd "$PROJECT_DIR"
if [[ ! -d .venv ]]; then
  echo ">> Creating Python virtualenv..."
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 6. .env
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo ">> Created .env (edit it to customise)"
fi

mkdir -p data logs

echo ""
echo "✓ Install complete."
echo "  Start the assistant with:  ./scripts/start.sh"
echo "  Then open:                 http://127.0.0.1:8000"

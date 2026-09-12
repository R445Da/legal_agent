#!/usr/bin/env bash
# Start the RAG server: local Ollama (if installed & not already running) +
# the FastAPI API on 0.0.0.0:8000. Ctrl-C stops uvicorn; Ollama is left running.
#
# Expose it to the internet in a second terminal with:
#     scripts/tunnel.sh
set -euo pipefail
cd "$(dirname "$0")/.."

OLLAMA_BIN="${OLLAMA_BIN:-$HOME/ollama/bin/ollama}"
[ -x "$OLLAMA_BIN" ] || OLLAMA_BIN="$(command -v ollama || true)"

if [ -n "$OLLAMA_BIN" ] && ! curl -sf http://localhost:11434/api/version >/dev/null 2>&1; then
  echo "starting ollama ($OLLAMA_BIN serve)…"
  nohup "$OLLAMA_BIN" serve > "$HOME/ollama-serve.log" 2>&1 &
  until curl -sf http://localhost:11434/api/version >/dev/null 2>&1; do sleep 1; done
fi

PORT="${PORT:-8000}"
echo "API on http://0.0.0.0:$PORT  (UI at /)"
exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port "$PORT"

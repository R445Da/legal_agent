#!/usr/bin/env bash
# Stop the Streamlit UI + the API console, then start them fresh.
# Run this after editing .env (a key, a model, a knob) — a running process
# keeps the .env it read at startup, so changes need a restart.
#
#   scripts/restart-ui.sh            # UI on :8501, console on :8000
#   UI_PORT=8502 scripts/restart-ui.sh
set -u
cd "$(dirname "$0")/.."

UI_PORT="${UI_PORT:-8501}"
API_PORT="${API_PORT:-8000}"
VENV=".venv/bin"

echo "· stopping old processes"
pkill -f 'streamlit run streamlit_app.py' 2>/dev/null && sleep 1 || true
pkill -f 'uvicorn app.main:app'          2>/dev/null && sleep 1 || true

# Ollama is the local-model backend and `stop.sh --all` can have stopped it.
# Prefer the tarball install: a stale /usr/local/bin/ollama answers /api/tags
# but 500s on every generate ("llama-server binary not found").
if ! curl -sf -o /dev/null --max-time 3 http://localhost:11434/api/version 2>/dev/null; then
  OLLAMA_BIN="${OLLAMA_BIN:-$HOME/ollama/bin/ollama}"
  [ -x "$OLLAMA_BIN" ] || OLLAMA_BIN="$(command -v ollama || true)"
  if [ -n "$OLLAMA_BIN" ]; then
    echo "· Ollama       -> starting ($OLLAMA_BIN)"
    nohup "$OLLAMA_BIN" serve > "$HOME/ollama-serve.log" 2>&1 &
    for _ in $(seq 1 15); do
      curl -sf -o /dev/null --max-time 2 http://localhost:11434/api/version 2>/dev/null && break
      sleep 1
    done
  else
    echo "· Ollama       -> binary not found; local models will be unavailable"
  fi
fi

echo "· API console  -> http://localhost:${API_PORT}  (logs: api.log)"
nohup "$VENV/uvicorn" app.main:app --host 127.0.0.1 --port "$API_PORT" \
      > api.log 2>&1 &

echo "· Streamlit UI -> http://localhost:${UI_PORT}   (logs: ui.log)"
nohup "$VENV/streamlit" run streamlit_app.py \
      --server.port "$UI_PORT" --server.headless true \
      > ui.log 2>&1 &

sleep 4
echo
echo "· active model (from .env):"
grep -E '^(LLM_PROVIDER|LLM_MODEL|GROQ_MODEL|ROUTER_MODEL)=' .env | sed 's/^/    /'
echo
echo "  open http://localhost:${UI_PORT} — pick the model in the left panel."
echo "  if a model shows ⚠, click «بازخوانی · اجرای Ollama» to re-check."

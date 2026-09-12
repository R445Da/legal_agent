#!/usr/bin/env bash
# One command to bring the whole stack up from cold and leave it running.
#
#   scripts/up.sh              # Ollama + API on :8000, using whatever .env says
#   LLM_PROVIDER=local scripts/up.sh   # force the fully-local path this run
#
# What it does, in order:
#   1. kills any stale uvicorn already holding :8000 / :8001
#   2. starts Ollama (:11434) if it isn't already up
#   3. makes sure the local model named in .env is pulled
#   4. starts 9router (:20128) *only if* a `9router` binary is on PATH
#   5. starts the FastAPI app on :8000 in the foreground (Ctrl-C stops it;
#      Ollama and 9router are left running)
#
# Open http://localhost:8000/app afterwards.
set -euo pipefail
cd "$(dirname "$0")/.."

# --- read a couple of keys out of .env (env vars still win) ------------------
env_get() { grep -E "^$1=" .env 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"'; }
LLM_PROVIDER="${LLM_PROVIDER:-$(env_get LLM_PROVIDER)}"
LLM_MODEL="${LLM_MODEL:-$(env_get LLM_MODEL)}"
PORT="${PORT:-8000}"
OLLAMA_BIN="${OLLAMA_BIN:-$HOME/ollama/bin/ollama}"
[ -x "$OLLAMA_BIN" ] || OLLAMA_BIN="$(command -v ollama || true)"

say() { printf '\033[36m▸ %s\033[0m\n' "$*"; }

# --- 1. clear stale API processes ------------------------------------------
for p in 8000 8001; do
  pids="$(ss -tlnp 2>/dev/null | awk -v P=":$p" '$4 ~ P {print $NF}' \
          | grep -oE 'pid=[0-9]+' | cut -d= -f2 | sort -u || true)"
  if [ -n "$pids" ]; then
    say "stopping stale server on :$p (pid $pids)"
    kill $pids 2>/dev/null || true
    sleep 1
  fi
done

# --- 2. Ollama ------------------------------------------------------------
if [ -n "$OLLAMA_BIN" ] && ! curl -sf http://localhost:11434/api/version >/dev/null 2>&1; then
  say "starting Ollama"
  nohup "$OLLAMA_BIN" serve > "$HOME/ollama-serve.log" 2>&1 &
  until curl -sf http://localhost:11434/api/version >/dev/null 2>&1; do sleep 1; done
fi
[ -n "$OLLAMA_BIN" ] && say "Ollama up ($(curl -s http://localhost:11434/api/version))"

# --- 3. make sure the local model is present ------------------------------
# (the assistant falls back to local for embeddings/reranking regardless of
#  provider, and any 'local::' model picked in the UI needs this too)
LOCAL_MODEL="qwen2.5:3b"
[ "$LLM_PROVIDER" = "local" ] && [ -n "$LLM_MODEL" ] && LOCAL_MODEL="$LLM_MODEL"
if [ -n "$OLLAMA_BIN" ] && ! "$OLLAMA_BIN" list 2>/dev/null | grep -q "^${LOCAL_MODEL}[[:space:]]"; then
  say "pulling $LOCAL_MODEL (one time)"
  "$OLLAMA_BIN" pull "$LOCAL_MODEL"
fi

# --- 4. 9router, only if installed ----------------------------------------
if [ "$LLM_PROVIDER" = "openai" ]; then
  if curl -sf http://localhost:20128/v1/models >/dev/null 2>&1; then
    say "9router already up on :20128"
  elif command -v 9router >/dev/null 2>&1; then
    say "starting 9router"
    nohup 9router > "$HOME/9router.log" 2>&1 &
    until curl -sf http://localhost:20128/ >/dev/null 2>&1; do sleep 1; done
  else
    cat >&2 <<'EOF'
▸ WARNING: .env has LLM_PROVIDER=openai / LLM_MODEL=combo, which routes through
  the 9router gateway on :20128 — but 9router is not running and no `9router`
  binary is on PATH. Cloud model calls (/ask, /assistant with `combo`) will
  fail with a connection error until you either:
    • install & start 9router and add its key to .env, OR
    • switch to local:  set LLM_PROVIDER=local and LLM_MODEL=qwen2.5:3b in .env
  Local models chosen in the UI model-picker still work regardless.
EOF
  fi
fi

# --- 5. the API ---------------------------------------------------------
say "API on http://0.0.0.0:$PORT   (UI at /app)"
exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port "$PORT"

#!/usr/bin/env bash
# بیمه ایران حقوقی — run the React front end (iran-insurance-legal/) against the API.
#
#   scripts/legal-web.sh               API (your .env) on :8000 + live UI on :5173
#   scripts/legal-web.sh --offline     same, but fully offline: mock LLM, hash
#                                      embeddings, and the seeded 120-case
#                                      insurance archive in .pgdata-legal-web
#                                      (never touches .pgdata)
#   scripts/legal-web.sh --build       build the UI once and serve it from the API
#                                      at http://localhost:8000/legal/  (combine
#                                      with --offline)
#
#   API_PORT=8010 WEB_PORT=5180 scripts/legal-web.sh --offline
#
# The UI binds 0.0.0.0 (like Streamlit does) so a Windows browser can reach it
# through WSL; set WEB_HOST=127.0.0.1 to keep it on loopback only.
#
# Ctrl-C stops everything this script started. The Streamlit app is untouched
# and can run beside it (scripts/restart-ui.sh).
set -euo pipefail
cd "$(dirname "$0")/.."

API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-5173}"
WEB_HOST="${WEB_HOST:-0.0.0.0}"
VENV="${VENV:-.venv}"
WEB_DIR="iran-insurance-legal"
OFFLINE=0
BUILD=0
for arg in "$@"; do
  case "$arg" in
    --offline) OFFLINE=1 ;;
    --build) BUILD=1 ;;
    -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

say() { printf '\033[36m▸ %s\033[0m\n' "$*"; }
die() { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

[ -x "$VENV/bin/uvicorn" ] || die "no $VENV/bin/uvicorn — create the venv first (uv venv --python 3.12 && uv pip install -r requirements.txt), or set VENV=/path/to/venv"
command -v node >/dev/null || die "node is not installed (Node 20.19+ is required for the UI)"

if [ "$OFFLINE" = 1 ]; then
  say "offline mode — mock model, hash embeddings, archive in .pgdata-legal-web"
  export LLM_PROVIDER=mock LLM_MODEL=rules-v1 ROUTER_MODEL=mock::rules-v1
  export EMBEDDING_MODEL=hash://384 EMBEDDING_DIM=384 EMBEDDING_PREFIXES=0
  export HYBRID=1 RERANK=0 TS_CONFIG=simple STT=0 SIMILAR_TOOL_BUDGET_S=0 LABELS_LLM=0
  export DATABASE_URL=embedded PG_DATA_DIR="$PWD/.pgdata-legal-web" API_TOKEN=
  if [ ! -f "$PG_DATA_DIR/.seeded" ]; then
    say "first run — seeding the insurance archive (120 cases, ~1 min)"
    "$VENV/bin/python" -m scripts.seed_mock --reset --n 120
    touch "$PG_DATA_DIR/.seeded"
  fi
fi

if [ ! -d "$WEB_DIR/node_modules" ]; then
  say "installing UI dependencies (one time)"
  (cd "$WEB_DIR" && npm install --no-audit --no-fund)
fi

# A stale server on the port would answer /health and hide this one.
if curl -sf -o /dev/null "http://127.0.0.1:$API_PORT/health"; then
  die "something is already serving :$API_PORT — stop it (scripts/stop.sh) or set API_PORT"
fi

pids=()
cleanup() { for p in "${pids[@]}"; do kill "$p" 2>/dev/null || true; done; }
trap cleanup EXIT INT TERM

if [ "$BUILD" = 1 ]; then
  say "building the UI"
  (cd "$WEB_DIR" && npm run build)
fi

say "API on http://127.0.0.1:$API_PORT"
"$VENV/bin/uvicorn" app.main:app --host 127.0.0.1 --port "$API_PORT" &
pids+=($!)
for _ in $(seq 1 90); do
  curl -sf -o /dev/null "http://127.0.0.1:$API_PORT/health" && break
  sleep 1
done
curl -sf -o /dev/null "http://127.0.0.1:$API_PORT/health" || die "the API did not come up — see the log above"

if [ "$BUILD" = 1 ]; then
  say "open  http://localhost:$API_PORT/legal/"
  wait "${pids[0]}"
else
  say "open  http://localhost:$WEB_PORT/"
  command -v hostname >/dev/null && hostname -I 2>/dev/null | awk '{print $1}' | xargs -I{} printf '\033[36m▸ or    http://%s:%s/  (from Windows, if localhost does not forward)\033[0m\n' {} "$WEB_PORT"
  (cd "$WEB_DIR" && LEGAL_API="http://127.0.0.1:$API_PORT" npx vite --host "$WEB_HOST" --port "$WEB_PORT" --strictPort) &
  pids+=($!)
  wait
fi

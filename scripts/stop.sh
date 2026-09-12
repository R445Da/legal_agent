#!/usr/bin/env bash
# Stop everything this project starts.
#
#   scripts/stop.sh            # UI + API console (leaves Ollama and Postgres alone)
#   scripts/stop.sh --all      # also stop Ollama and the embedded Postgres
#
# Ollama and the embedded Postgres are shared/slow to restart, so they survive
# by default — `restart-ui.sh` reuses them.
set -u
cd "$(dirname "$0")/.."
ALL=0; [ "${1:-}" = "--all" ] && ALL=1

G="\033[32m"; DIM="\033[2m"; OFF="\033[0m"
gone() { printf "  ${G}✓${OFF} %s\n" "$1"; }
skip() { printf "  ${DIM}·${OFF} %s\n" "$1"; }

# $1 = label, $2 = pgrep -f pattern
stop() {
  local label="$1" pat="$2" pids
  pids=$(pgrep -f "$pat" 2>/dev/null | grep -v "^$$\$")
  if [ -z "$pids" ]; then skip "$label — not running"; return; fi
  kill $pids 2>/dev/null
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    sleep 0.3
    pgrep -f "$pat" >/dev/null 2>&1 || { gone "$label  (stopped $(echo $pids | wc -w))"; return; }
  done
  kill -9 $(pgrep -f "$pat") 2>/dev/null   # stubborn: SIGKILL
  gone "$label  (forced)"
}

echo
stop "Streamlit UI"  "streamlit run streamlit_app.py"
stop "API console"   "uvicorn app.main:app"

if [ "$ALL" = "1" ]; then
  stop "Ollama"      "ollama serve"
  # pgserver's cluster — stop it politely so it doesn't need recovery on boot.
  if [ -d .pgdata ] && command -v pg_ctl >/dev/null 2>&1; then
    pg_ctl -D .pgdata stop -m fast >/dev/null 2>&1 && gone "Postgres (.pgdata)" \
      || skip "Postgres — not running or not stoppable here"
  else
    stop "Postgres"  "postgres -D .*\.pgdata"
  fi
else
  skip "Ollama, Postgres — left running (use --all to stop them)"
fi

echo
for p in 8501 8000 3000; do
  if ss -ltn 2>/dev/null | grep -q ":$p "; then
    printf "  \033[33m!\033[0m port %s still listening\n" "$p"
  fi
done
echo -e "  ${DIM}restart with: scripts/restart-ui.sh${OFF}\n"

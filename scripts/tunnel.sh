#!/usr/bin/env bash
# Put the running app on a public HTTPS URL, free, without deploying anything.
#
#   scripts/tunnel.sh              # the Streamlit UI (:8501)
#   scripts/tunnel.sh 8000         # the run console instead
#   TUNNEL=cloudflare scripts/tunnel.sh
#
# Your machine still does the work — this only forwards traffic to it. Close
# the terminal and the URL dies. That is the whole appeal: nothing to deploy,
# nothing to pay for, and the archive never leaves your disk.
#
# ── cloudflared (no account needed) ────────────────────────────────
#   curl -L -o ~/.local/bin/cloudflared \
#     https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
#   chmod +x ~/.local/bin/cloudflared
#   Gives a random trycloudflare.com URL. No signup, no token, no time limit.
#
# ── ngrok (account, already installed here) ───────────────────────
#   ngrok config add-authtoken <token from dashboard.ngrok.com>
#
# WARNING: this exposes the app to anyone with the link. The Streamlit UI has
# NO login. Only the API on :8000 is protected, by API_TOKEN. Do not leave a
# tunnel to :8501 running unattended with real case data behind it.
set -u
cd "$(dirname "$0")/.." 2>/dev/null || true

PORT="${1:-8501}"
TUNNEL="${TUNNEL:-auto}"

if ! curl -sf -o /dev/null --max-time 3 "http://localhost:${PORT}" 2>/dev/null; then
  echo "· nothing is listening on :${PORT} — run scripts/restart-ui.sh first"
  exit 1
fi

CF="${CLOUDFLARED_BIN:-$HOME/.local/bin/cloudflared}"
[ -x "$CF" ] || CF="$(command -v cloudflared || true)"
NG="${NGROK_BIN:-$HOME/.local/bin/ngrok}"
[ -x "$NG" ] || NG="$(command -v ngrok || true)"

case "$TUNNEL" in
  cloudflare) NG="" ;;
  ngrok)      CF="" ;;
esac

echo
echo "· forwarding localhost:${PORT} to the internet"
[ "$PORT" = "8501" ] && echo "  ⚠ the Streamlit UI has no login — anyone with the link gets in"
echo

if [ -n "${CF:-}" ]; then
  exec "$CF" tunnel --url "http://localhost:${PORT}"
elif [ -n "${NG:-}" ]; then
  exec "$NG" http "$PORT"
else
  echo "  neither cloudflared nor ngrok found."
  echo "  cloudflared needs no account — see the install line at the top of this file."
  exit 1
fi

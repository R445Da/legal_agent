#!/usr/bin/env bash
# The outbound-webhook demo, end to end, against a running API:
#   1. start scripts/hook_sink.py and register it as a subscription (signed),
#   2. file one entry through the conversation API (POST /runs … /reply),
#   3. show the signed deliveries the sink received (run.status, entry.committed, …).
#
#   BASE=http://127.0.0.1:8000 API_TOKEN=… scripts/demo_hooks.sh
#   EVENTS=entry.committed,run.status,answer.created PORT=8099 scripts/demo_hooks.sh
set -uo pipefail
cd "$(dirname "$0")/.."
export BASE="${BASE:-http://127.0.0.1:8000}"
export API_TOKEN="${API_TOKEN:-$(grep -E '^API_TOKEN=' .env 2>/dev/null | cut -d= -f2-)}"
PORT="${PORT:-8099}"
EVENTS="${EVENTS:-entry.committed,run.status,answer.created}"
PY="${PY:-.venv/bin/python}"

echo "== sink on :$PORT, subscribed to $EVENTS"
"$PY" -m scripts.hook_sink --register --port "$PORT" --events "$EVENTS" &
SINK=$!
sleep 3

echo "== filing one entry through the conversation API"
"$PY" -m scripts.conversation_probe | tail -3

echo "== waiting for deliveries (the API drains its outbox every 3 s)"
sleep 8
kill "$SINK" 2>/dev/null
wait "$SINK" 2>/dev/null
echo "== deliveries as the API recorded them"
curl -s -H "authorization: Bearer $API_TOKEN" "$BASE/hooks/deliveries?limit=8" | "$PY" - <<'PYEOF'
import json, sys
for d in json.load(sys.stdin)["deliveries"]:
    print(f"{d['status']:<8} {d['event']:<18} attempts={d['attempts']} code={d.get('response_code')}  {(d.get('error') or '')[:50]}")
PYEOF

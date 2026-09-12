#!/usr/bin/env bash
# Watch data/inbox/ and automatically index + extract anything dropped in.
#
#   scripts/watch.sh                 # poll data/inbox every 20s
#   INBOX=data/new INTERVAL=10 scripts/watch.sh
#
# Drop .txt files into data/inbox/ (from a file manager, scp, a script, whatever).
# Each is chunked + embedded + structure-extracted (an Entry row), then moved to
# data/inbox/done/ so it isn't processed twice. Ctrl-C to stop.
#
# This is the "same process every time a document is added" path for bulk/folder
# input. Documents added through the UI's "بایگانی سند جدید" screen, or via
# POST /ingest, already get the same treatment automatically.
set -euo pipefail
cd "$(dirname "$0")/.."

INBOX="${INBOX:-data/inbox}"
INTERVAL="${INTERVAL:-20}"
mkdir -p "$INBOX/done"

echo "watching $INBOX/  (every ${INTERVAL}s)  — drop .txt files in; Ctrl-C to stop"
while true; do
  if compgen -G "$INBOX/*.txt" > /dev/null; then
    n=$(find "$INBOX" -maxdepth 1 -name '*.txt' | wc -l)
    echo "$(date +%H:%M:%S)  processing $n file(s)…"
    .venv/bin/python -m scripts.add "$INBOX" --move-to "$INBOX/done" || echo "  (a file failed — see above; it stays in $INBOX)"
  fi
  sleep "$INTERVAL"
done

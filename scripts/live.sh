#!/usr/bin/env bash
# The live terminal sandbox. Forwards every flag to scripts/live_console.py.
#
#   scripts/live.sh                       typed input, gates at every step
#   scripts/live.sh --mic                 microphone, live transcription
#   scripts/live.sh --file session.mp3
#   scripts/live.sh --text "..." --yes    one shot, no prompts
#   scripts/live.sh --model "local::qwen2.5:3b" --mode review
set -euo pipefail
cd "$(dirname "$0")/.."
[ -x .venv/bin/python ] || { echo "[error] no .venv - see README (uv venv --python 3.12)"; exit 1; }
.venv/bin/python -c "import google.genai" 2>/dev/null || {
  echo "[setup] installing google-genai + sounddevice (live transcription)"
  .venv/bin/pip -q install -U google-genai sounddevice
}
exec .venv/bin/python -m scripts.live_console "$@"

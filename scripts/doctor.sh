#!/usr/bin/env bash
# One command that tells you what is and isn't working.
# Run this FIRST whenever the app misbehaves — especially when Groq goes quiet.
#
#   scripts/doctor.sh
set -u
cd "$(dirname "$0")/.."
V=".venv/bin"
ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$1"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$1"; }

echo
echo "── servers ──────────────────────────────────────────"
for s in "Streamlit UI|8501|/_stcore/health" "API console|8000|/health" "Ollama|11434/api/version|"; do
  IFS='|' read -r name port path <<< "$s"
  url="http://localhost:${port}${path}"
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 4 "$url" 2>/dev/null)
  [ "$code" = "200" ] && ok "$name  ($code)" || bad "$name  ($code)  — start it: scripts/restart-ui.sh"
done

echo
echo "── groq ─────────────────────────────────────────────"
KEY=$(grep -E '^GROQ_API_KEY=' .env 2>/dev/null | cut -d= -f2)
if [ -z "${KEY:-}" ]; then
  warn "no GROQ_API_KEY in .env"
else
  # THE decisive test: no key at all.
  #   401 -> endpoint reachable, auth evaluated  => a 403 with a key is the NETWORK
  #   403 -> blocked before auth                 => no key can fix it
  noauth=$(curl -s -o /dev/null -w '%{http_code}' --max-time 12 https://api.groq.com/openai/v1/models 2>/dev/null)
  withkey=$(curl -s -o /dev/null -w '%{http_code}' --max-time 12 \
            -H "Authorization: Bearer $KEY" -H 'User-Agent: Mozilla/5.0' \
            https://api.groq.com/openai/v1/models 2>/dev/null)
  # Which exit node are we leaving from? Groq blocks datacenter/VPN IP ranges,
  # so the answer flips with the VPN server, not with the clock.
  edge=$(curl -s -D - -o /dev/null --max-time 10 https://api.groq.com/openai/v1/models 2>/dev/null \
         | grep -i '^cf-ray:' | tr -d '\r' | awk -F- '{print $NF}')
  egress=$(curl -s --max-time 8 https://ipinfo.io/json 2>/dev/null \
           | tr -d '",{}' | awk -F: '/^[[:space:]]*(ip|country|org)/{gsub(/^ +| +$/,"",$2); printf "%s ", $2}')
  echo "     keyless=$noauth   with-key=$withkey"
  [ -n "${egress:-}" ] && echo "     egress:  $egress"
  [ -n "${edge:-}"   ] && echo "     cf edge: $edge"
  if   [ "$withkey" = "200" ]; then ok  "Groq reachable, key valid"
  elif [ "$noauth"  = "403" ]; then
    bad "Cloudflare is blocking this network — 403 arrives BEFORE auth (keyless is 403, not 401),"
    echo "       so NO key can fix this. Replacing GROQ_API_KEY will not help."
    echo "       This tracks your VPN EXIT NODE, not the clock — Groq blocks"
    echo "       datacenter/VPN IP ranges. Switching VPN server (or turning it off)"
    echo "       usually fixes it in seconds; re-run this script to confirm."
    echo "       Or fall back to local:"
    echo "         sed -i 's|^LLM_PROVIDER=.*|LLM_PROVIDER=local|;   s|^LLM_MODEL=.*|LLM_MODEL=qwen2.5:3b|' .env"
    echo "         sed -i 's|^ROUTER_MODEL=.*|ROUTER_MODEL=local::qwen2.5:7b|' .env"
    echo "         scripts/restart-ui.sh"
  elif [ "$withkey" = "403" ]; then warn "403 with key but keyless=$noauth — geo-block is FLAPPING. Retries absorb most of it; try again."
  elif [ "$withkey" = "401" ]; then bad "401 — the key really is invalid. Replace GROQ_API_KEY in .env, then scripts/restart-ui.sh"
  else                              bad "unexpected: $withkey"
  fi
fi

echo
echo "── models the app can actually use ──────────────────"
PYTHONPATH="$PWD" "$V/python" -c "
from dotenv import load_dotenv; load_dotenv('.env', override=True)
from app.llm import registry
c = registry.catalog(autostart_ollama=False)
for e in c:
    print(('  \033[32m✓\033[0m ' if e['available'] else '  \033[31m✗\033[0m ') + e['id']
          + ('' if e['available'] else '  — ' + (e.get('reason') or '')[:60]))
print(f\"    {sum(1 for e in c if e['available'])}/{len(c)} usable · default: {registry.default_id()}\")
" 2>/dev/null | grep -v '^$'

echo
echo "── config in .env ───────────────────────────────────"
grep -E '^(LLM_PROVIDER|LLM_MODEL|ROUTER_MODEL|GROQ_MODEL)=' .env | sed 's/^/  /'
echo

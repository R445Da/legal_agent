#!/usr/bin/env bash
# Will Groq work from this network — or from a proxy you are considering buying?
#
#   scripts/check-exit.sh                          # test the current connection
#   scripts/check-exit.sh socks5://127.0.0.1:1080  # test through a proxy first
#   scripts/check-exit.sh http://user:pass@host:8080
#
# Run it BEFORE paying for anything. Most VPN/proxy providers give a trial
# endpoint or a refund window — point this at it and you get a yes/no in ~5s.
set -u
cd "$(dirname "$0")/.." 2>/dev/null || true
PROXY="${1:-}"
P=(); [ -n "$PROXY" ] && P=(--proxy "$PROXY")

G="\033[32m"; R="\033[31m"; Y="\033[33m"; D="\033[2m"; O="\033[0m"

echo
[ -n "$PROXY" ] && echo "  via proxy: $PROXY" || echo "  via: this machine's current connection"
echo "  ────────────────────────────────────────────────"

# Who do we look like?
info=$(curl -s "${P[@]}" --max-time 12 https://ipinfo.io/json 2>/dev/null)
ip=$(echo "$info"  | tr -d '",{}' | awk -F: '/^[[:space:]]*ip/{gsub(/^ +| +$/,"",$2); print $2}')
org=$(echo "$info" | tr -d '",{}' | awk -F: '/^[[:space:]]*org/{gsub(/^ +| +$/,"",$2); print $2}')
cc=$(echo "$info"  | tr -d '",{}' | awk -F: '/^[[:space:]]*country/{gsub(/^ +| +$/,"",$2); print $2}')

if [ -z "${ip:-}" ]; then
  printf "  ${R}✗${O} could not reach ipinfo.io — the proxy itself may be down\n\n"; exit 1
fi
printf "  egress   %s  (%s)\n" "$ip" "${cc:-?}"
printf "  operator %s\n" "${org:-unknown}"

# Datacenter or residential? Groq blocks the former.
if echo "${org:-}" | grep -qiE 'hosting|cloud|server|data ?cent|colo|vps|dedicated|digitalocean|linode|vultr|ovh|hetzner|amazon|google|microsoft|azure|contabo|choopa|tzulo|leaseweb|m247|datacamp'; then
  printf "  type     ${Y}datacenter / hosting${O}  ← the category Groq blocks\n"
else
  printf "  type     ${G}looks residential / ISP${O}\n"
fi
echo

# The verdict that actually matters.
KEY=$(grep -E '^GROQ_API_KEY=' .env 2>/dev/null | cut -d= -f2)
noauth=$(curl -s "${P[@]}" -o /dev/null -w '%{http_code}' --max-time 15 \
         https://api.groq.com/openai/v1/models 2>/dev/null)
printf "  groq (no key)  %s   " "$noauth"
case "$noauth" in
  401) printf "${G}reachable — auth is being evaluated${O}\n" ;;
  403) printf "${R}BLOCKED before auth — no key helps here${O}\n" ;;
  000) printf "${R}no response (proxy down or DNS blocked)${O}\n" ;;
  *)   printf "${Y}unexpected${O}\n" ;;
esac

if [ -n "${KEY:-}" ]; then
  withkey=$(curl -s "${P[@]}" -o /dev/null -w '%{http_code}' --max-time 15 \
            -H "Authorization: Bearer $KEY" -H 'User-Agent: Mozilla/5.0' \
            https://api.groq.com/openai/v1/models 2>/dev/null)
  printf "  groq (keyed)   %s   " "$withkey"
  case "$withkey" in
    200) printf "${G}WORKS${O}\n" ;;
    403) printf "${R}blocked${O}\n" ;;
    401) printf "${Y}reachable, but the key is invalid${O}\n" ;;
    *)   printf "${Y}unexpected${O}\n" ;;
  esac
fi

echo
if [ "${withkey:-}" = "200" ]; then
  printf "  ${G}VERDICT: this exit works. Safe to use / buy.${O}\n"
elif [ "$noauth" = "403" ]; then
  printf "  ${R}VERDICT: this exit is blocked. Do not buy it for Groq.${O}\n"
  printf "  ${D}A VPS is always a datacenter IP — that is the blocked category.${O}\n"
  printf "  ${D}You need a residential exit, or just your own ISP.${O}\n"
else
  printf "  ${Y}VERDICT: inconclusive — retry, the block flaps.${O}\n"
fi
echo

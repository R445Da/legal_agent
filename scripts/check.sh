#!/usr/bin/env bash
# Smoke-test every endpoint. Prints PASS/FAIL per check.
#   scripts/check.sh                 # against localhost:8000
#   BASE=https://x.ngrok-free.app scripts/check.sh
#   API_TOKEN=… scripts/check.sh    # no .env (CI, Codespaces secrets)
set -uo pipefail
cd "$(dirname "$0")/.."

BASE="${BASE:-http://localhost:8000}"
TOKEN="${API_TOKEN:-$(grep -E '^API_TOKEN=' .env 2>/dev/null | cut -d= -f2-)}"
AUTH=(-H "authorization: Bearer $TOKEN")
pass=0; fail=0

check() { # name  expected-substring  curl-args...
  local name="$1" want="$2"; shift 2
  local out; out="$(curl -s --max-time 240 "$@" 2>&1)"
  if grep -q "$want" <<<"$out"; then echo "PASS  $name"; ((pass++))
  else echo "FAIL  $name"; echo "      got: ${out:0:200}"; ((fail++)); fi
}

echo "== $BASE =="
check "health"          '"status":"ok"'        "$BASE/health"
check "models list"     '"models"'             "${AUTH[@]}" "$BASE/models"
check "search (fa)"     '"hits"'               "${AUTH[@]}" -X POST "$BASE/search" \
      -H 'content-type: application/json' -d '{"query":"چک برگشتی بانک ملت","top_k":3}'
check "ask (fa)"        '"answer"'             "${AUTH[@]}" -X POST "$BASE/ask" \
      -H 'content-type: application/json' -d '{"question":"در پرونده کالای معیوب دادگاه چه تصمیمی گرفت؟"}'
check "assistant query" '"intent":"query"'     "${AUTH[@]}" -X POST "$BASE/assistant" \
      -H 'content-type: application/json' -d '{"intent":"query","text":"چند پرونده کارگری داریم؟"}'
check "assistant archive" '"draft"'            "${AUTH[@]}" -X POST "$BASE/assistant" \
      -H 'content-type: application/json' -d '{"intent":"archive","text":"جلسه پرونده ۹۹ شعبه ۱. خواهان شرکت الف با وکالت آقای کریمی، خوانده آقای مرادی. مطالبه وجه. قاضی به کارشناسی ارجاع داد."}'
check "stats"           '"lawyers"'            "${AUTH[@]}" "$BASE/stats"
check "entries"         '\['                   "${AUTH[@]}" "$BASE/entries"
check "documents"       '\['                   "${AUTH[@]}" "$BASE/documents"
check "eval"            '"metrics"'            "${AUTH[@]}" -X POST "$BASE/eval" \
      -H 'content-type: application/json' -d '{"top_k":5}'
check "assistant law + provenance" '"provenance"' "${AUTH[@]}" -X POST "$BASE/assistant" \
      -H 'content-type: application/json' -d '{"intent":"law","text":"ماده ۳۰ قانون بیمه چه می‌گوید؟"}'
check "assistant law + similar cases" '"similar_cases"' "${AUTH[@]}" -X POST "$BASE/assistant" \
      -H 'content-type: application/json' -d '{"intent":"law","text":"ماده ۳۰ قانون بیمه دربارهٔ جانشینی چه می‌گوید؟"}'
check "assistant agent"  '"tool_trail"'         "${AUTH[@]}" -X POST "$BASE/assistant" \
      -H 'content-type: application/json' -d '{"intent":"agent","text":"پرونده‌های بازیافت از رانندهٔ مقصر طبق ماده ۱۶ چطور تمام شده‌اند؟"}'
check "answers"         '"answers"'            "${AUTH[@]}" "$BASE/answers?limit=5"
check "run start (conversation)" '"waiting":true' "${AUTH[@]}" -X POST "$BASE/runs" \
      -H 'content-type: application/json' -d '{"mode":"conversation","text":"صورت‌جلسه شعبه ۱. خواهان شرکت الف با وکالت آقای کریمی، خوانده آقای مرادی. موضوع: مطالبه وجه. قاضی به کارشناسی ارجاع داد."}'
check "auth enforced"   '401'                  -o /dev/null -w '%{http_code}' -X POST "$BASE/ask" \
      -H 'content-type: application/json' -d '{"question":"x"}'

echo "-- $pass passed, $fail failed --"
exit $((fail > 0))

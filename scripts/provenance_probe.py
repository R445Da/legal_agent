"""
Ask the running API one question and print what the answer rests on.

    python -m scripts.provenance_probe "ماده ۳۰ قانون بیمه چه می‌گوید؟" --intent law
    python -m scripts.provenance_probe "پرونده‌های بازیافت چطور تمام شده‌اند؟" --intent agent
    BASE=http://127.0.0.1:8010 API_TOKEN=citoken python -m scripts.provenance_probe ...

Prints the intent, the tool trail, the numbered evidence, the citation check
and the token bill — the same block the chat shows under an answer and the
`assistant_answers` table keeps. Exit code 1 when the grounding status is
`unsupported`, so it doubles as a smoke check.
"""

import argparse
import json
import os
import sys
import urllib.request


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("text")
    ap.add_argument("--intent", default=None, help="query | law | cases | agent (default: let the router decide)")
    ap.add_argument("--base", default=os.environ.get("BASE", "http://127.0.0.1:8000"))
    ap.add_argument("--token", default=os.environ.get("API_TOKEN", ""))
    ap.add_argument("--raw", action="store_true", help="dump the whole response")
    args = ap.parse_args()

    body = json.dumps({"text": args.text, "intent": args.intent}).encode()
    req = urllib.request.Request(
        f"{args.base}/assistant", data=body, method="POST",
        headers={"content-type": "application/json",
                 **({"authorization": f"Bearer {args.token}"} if args.token else {})},
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        data = json.load(resp)

    if args.raw:
        print(json.dumps(data, ensure_ascii=False, indent=1))
        return 0

    prov = data.get("provenance") or {}
    grounding = prov.get("grounding") or {}
    print(f"intent     {data.get('intent')}   model {prov.get('model')}   loop {prov.get('loop', '-')}")
    print(f"answer     {(data.get('answer') or '')[:200].replace(chr(10), ' ')}")
    for row in prov.get("tool_trail") or []:
        print(f"tool       {row.get('tool'):<16} {row.get('summary')}   evidence {row.get('evidence_ns')}   {row.get('ms')} ms")
    for item in prov.get("evidence") or []:
        print(f"evidence   [{item.get('n')}] {item.get('label')}")
    for c in data.get("similar_cases") or []:
        why = "؛ ".join(c.get("why") or [])
        print(f"similar    {c.get('case_number')}  score {c.get('score')}  {(c.get('outcome') or '')[:50]}  ← {why}")
    if data.get("lessons"):
        print(f"lessons    {data['lessons'].get('summary')}")
    if data.get("advice"):
        print(f"advice     {data['advice'][:200].replace(chr(10), ' ')}")
    print(f"grounding  {grounding.get('status')}   coverage {grounding.get('coverage')}   "
          f"cited {grounding.get('cited')}   invalid {grounding.get('invalid')}")
    print(f"usage      {prov.get('usage')}")
    print(f"answer_id  {data.get('answer_id')}")
    return 1 if grounding.get("status") == "unsupported" else 0


if __name__ == "__main__":
    sys.exit(main())

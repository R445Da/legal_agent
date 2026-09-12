"""
Drive a conversation-mode filing through the running API, turn by turn.

    python -m scripts.conversation_probe                      # built-in sample, answers itself
    python -m scripts.conversation_probe --file samples/laheye-defaeiye.txt
    python -m scripts.conversation_probe --reply "شماره پرونده: ۱۴۰۲۰۰۱۲۳۴" --reply "تأیید"
    BASE=http://127.0.0.1:8010 API_TOKEN=citoken python -m scripts.conversation_probe

Starts the run with POST /runs {"mode": "conversation"}, prints the assistant's
question, sends each --reply with POST /runs/{id}/reply, and stops when the run
commits, is abandoned, or the replies run out. Exit code 0 only when the run
ends `committed`, so it doubles as a smoke check.
"""

import argparse
import json
import os
import sys
import urllib.request

SAMPLE = (
    "صورت‌جلسهٔ رسیدگی شعبهٔ ۳ دادگاه حقوقی تهران\n"
    "خواهان: شرکت سهامی بیمه ایران (با وکالت آقای رضا کریمی)\n"
    "خوانده: آقای علی مرادی\n"
    "موضوع: بازیافت خسارت پرداختی از رانندهٔ مقصر\n"
    "دادگاه با استناد به ماده ۳۰ قانون بیمه موضوع را به کارشناسی ارجاع داد."
)
DEFAULT_REPLIES = ["شماره پرونده: ۱۴۰۲۰۰۹۹۸۸", "تأیید"]


def _post(base: str, token: str, path: str, body: dict) -> dict:
    req = urllib.request.Request(
        f"{base}{path}", data=json.dumps(body).encode(), method="POST",
        headers={"content-type": "application/json",
                 **({"authorization": f"Bearer {token}"} if token else {})},
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.load(resp)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", help="text to file (default: a built-in sample without a case number)")
    ap.add_argument("--reply", action="append", help="answers to send, in order (repeatable)")
    ap.add_argument("--base", default=os.environ.get("BASE", "http://127.0.0.1:8000"))
    ap.add_argument("--token", default=os.environ.get("API_TOKEN", ""))
    args = ap.parse_args()

    text = open(args.file, encoding="utf-8").read() if args.file else SAMPLE
    replies = args.reply or DEFAULT_REPLIES

    out = _post(args.base, args.token, "/runs", {"text": text, "mode": "conversation", "source": "probe/conversation"})
    run = out["run"]
    print(f"run        {run['id']}   status {run['status']}")
    print("assistant  " + (out.get("message") or "—").replace("\n", "\n           "))

    for reply in replies:
        if not out.get("waiting"):
            break
        print(f"user       {reply}")
        out = _post(args.base, args.token, f"/runs/{run['id']}/reply", {"text": reply})
        run = out["run"]
        if out.get("waiting"):
            print("assistant  " + (out.get("message") or "—").replace("\n", "\n           "))
        else:
            print(f"status     {run['status']}   entry {run.get('entry_id') or '—'}")

    draft = (run.get("state") or {}).get("draft") or {}
    print(f"draft      title={draft.get('title')!r}  case_number={(draft.get('entities') or {}).get('case_number')!r}")
    return 0 if run["status"] == "committed" else 1


if __name__ == "__main__":
    sys.exit(main())

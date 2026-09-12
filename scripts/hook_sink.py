"""
A tiny receiver for the app's outbound webhooks — the other end of a demo.

    python -m scripts.hook_sink --port 8099 --secret <secret from POST /hooks>

Prints every delivery with its event, id and whether the HMAC signature
verified. Register it with:

    curl -X POST $BASE/hooks -H "authorization: Bearer $API_TOKEN" -H "content-type: application/json" \\
         -d '{"url":"http://127.0.0.1:8099/hook","events":["*"],"description":"demo sink"}'

and use the `secret` from the response as --secret.
"""

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, __import__("pathlib").Path(__file__).resolve().parents[1].as_posix())

from app.rag.hooks import verify  # noqa: E402


def make_handler(secret: str):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("content-length") or 0)
            body = self.rfile.read(length)
            ok = verify(secret, body, self.headers.get("X-Legal-Signature-256")) if secret else None
            try:
                data = json.loads(body.decode("utf-8"))
            except json.JSONDecodeError:
                data = {"raw": body[:200].decode("utf-8", "replace")}
            mark = "✓ signed" if ok else ("✗ BAD SIGNATURE" if ok is False else "unverified")
            print(f"{mark}  {self.headers.get('X-Legal-Event', '?'):<16} {self.headers.get('X-Legal-Delivery', '')}  "
                  f"{json.dumps(data.get('data', data), ensure_ascii=False)[:160]}", flush=True)
            self.send_response(200 if ok is not False else 401)
            self.end_headers()
            self.wfile.write(b"ok" if ok is not False else b"bad signature")

        def log_message(self, *_):  # quiet
            return

    return Handler


def register(base: str, token: str, url: str, events: list[str]) -> str:
    """Create the subscription through the API; returns its signing secret."""
    import urllib.request

    body = json.dumps({"url": url, "events": events, "description": "scripts/hook_sink.py"}).encode()
    req = urllib.request.Request(f"{base}/hooks", data=body, method="POST", headers={
        "content-type": "application/json", **({"authorization": f"Bearer {token}"} if token else {})})
    with urllib.request.urlopen(req, timeout=30) as resp:
        created = json.load(resp)
    print(f"registered subscription {created['id']} for {', '.join(events)}", flush=True)
    return created["secret"]


def main() -> int:
    import os

    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8099)
    ap.add_argument("--secret", default="")
    ap.add_argument("--register", action="store_true", help="create the subscription via the API on start")
    ap.add_argument("--base", default=os.environ.get("BASE", "http://127.0.0.1:8000"))
    ap.add_argument("--token", default=os.environ.get("API_TOKEN", ""))
    ap.add_argument("--events", default="*", help="comma-separated, with --register")
    args = ap.parse_args()
    if args.register:
        args.secret = register(args.base, args.token, f"http://127.0.0.1:{args.port}/hook",
                               [e.strip() for e in args.events.split(",") if e.strip()])
    server = HTTPServer(("127.0.0.1", args.port), make_handler(args.secret))
    print(f"listening on http://127.0.0.1:{args.port}/hook  (signature check: {'on' if args.secret else 'off'})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Webhooks: signing, the outbox, delivery and retries; CI event folding."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.rag import ci, hooks


def test_sign_verify_roundtrip_and_tamper():
    body = b'{"event":"ping","data":{"x":1}}'
    header = hooks.sign("s3cret", body)
    assert header.startswith("sha256=") and len(header) == 7 + 64
    assert hooks.verify("s3cret", body, header)
    assert hooks.verify("s3cret", body, " " + header + " ")
    assert not hooks.verify("s3cret", body + b" ", header)
    assert not hooks.verify("other", body, header)
    assert not hooks.verify("s3cret", body, None) and not hooks.verify("", body, header)


def test_event_matching():
    assert hooks.matches(["*"], "run.step")
    assert hooks.matches(["run.*"], "run.status") and not hooks.matches(["run.*"], "entry.committed")
    assert hooks.matches(["entry.committed"], "entry.committed") and not hooks.matches([], "ping")


def test_allowed_url(monkeypatch):
    monkeypatch.delenv("WEBHOOK_ALLOWED_HOSTS", raising=False)
    assert hooks.allowed_url("http://127.0.0.1:8099/hook") and hooks.allowed_url("https://example.com/x")
    assert not hooks.allowed_url("ftp://example.com") and not hooks.allowed_url("not a url")
    monkeypatch.setenv("WEBHOOK_ALLOWED_HOSTS", "hooks.example.com, localhost")
    assert hooks.allowed_url("http://localhost:1/x") and not hooks.allowed_url("http://127.0.0.1/x")


# --------------------------------------------------------------------------- #
class _Sink:
    """A local receiver: records requests, answers with a chosen status code."""

    def __init__(self, status: int = 200):
        self.status = status
        self.received: list[dict] = []
        sink = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("content-length") or 0)
                body = self.rfile.read(length)
                sink.received.append({"headers": dict(self.headers), "body": body})
                self.send_response(sink.status)
                self.end_headers()
                self.wfile.write(b"ok")

            def log_message(self, *_):
                return

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}/hook"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()


@pytest.mark.db
async def test_outbox_delivers_signed_and_retries(db_session, db_engine):
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import WebhookDelivery

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    good, bad = _Sink(200), _Sink(500)
    try:
        sub_ok = await hooks.create_subscription(db_session, url=good.url, events=["run.*", "ping"], description="ok")
        sub_bad = await hooks.create_subscription(db_session, url=bad.url, events=["*"], description="bad")

        queued = await hooks.emit(db_session, "run.step", {"run_id": "r1", "step_id": "extract", "status": "done"})
        await db_session.commit()
        assert queued == 2
        assert await hooks.emit(db_session, "entry.committed", {"entry_id": "e1"}) == 1  # only the "*" one
        await db_session.commit()

        tried = await hooks.drain(factory)
        assert tried == 3

        assert len(good.received) == 1
        req = good.received[0]
        assert req["headers"]["X-Legal-Event"] == "run.step"
        assert hooks.verify(sub_ok.secret, req["body"], req["headers"]["X-Legal-Signature-256"])
        envelope = json.loads(req["body"])
        assert envelope["data"]["step_id"] == "extract" and envelope["id"] == req["headers"]["X-Legal-Delivery"]

        rows = (await db_session.execute(select(WebhookDelivery).order_by(WebhookDelivery.created_at))).scalars().all()
        by_sub = {}
        for r in rows:
            by_sub.setdefault(r.subscription_id, []).append(r)
        ok_rows = by_sub[sub_ok.id]
        assert ok_rows[0].status == "sent" and ok_rows[0].response_code == 200 and ok_rows[0].sent_at
        bad_rows = by_sub[sub_bad.id]
        assert all(r.status == "failed" and r.attempts == 1 and "HTTP 500" in r.error for r in bad_rows)
        assert all(r.next_attempt_at > r.created_at for r in bad_rows)

        # nothing is due right now, so a second drain sends nothing
        assert await hooks.drain(factory) == 0

        # after the last allowed attempt a failing delivery is dead
        for r in bad_rows:
            r.attempts = hooks.MAX_ATTEMPTS - 1
            r.next_attempt_at = r.created_at
        await db_session.commit()
        await hooks.drain(factory)
        await db_session.refresh(bad_rows[0])
        assert bad_rows[0].status == "dead"
    finally:
        good.close()
        bad.close()
        await hooks.delete_subscription(db_session, sub_ok.id)
        await hooks.delete_subscription(db_session, sub_bad.id)


@pytest.mark.db
async def test_pipeline_run_emits_events(db_session, db_engine):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.llm.mock_provider import MockProvider
    from app.rag import workflow

    sink = _Sink(200)
    try:
        sub = await hooks.create_subscription(db_session, url=sink.url, events=["run.status", "entry.committed"])
        text = ("صورت‌جلسهٔ پروندهٔ کلاسه ۱۴۰۲۷۷۸۸۹۹ شعبهٔ ۲ دادگاه حقوقی. خواهان: شرکت سهامی بیمه ایران، "
                "خوانده: آقای حسن رضایی. موضوع: مطالبهٔ خسارت. دادگاه با استناد به ماده ۱۹ قانون بیمه رأی داد.")
        view = await workflow.start(db_session, raw_text=text, source="test/hooks", llm=MockProvider(),
                                    mode="auto", forced_intent="archive")
        assert view["status"] == "committed"
        await hooks.drain(async_sessionmaker(db_engine, expire_on_commit=False))
        events = [r["headers"]["X-Legal-Event"] for r in sink.received]
        assert "entry.committed" in events and "run.status" in events
        committed = next(json.loads(r["body"]) for r in sink.received if r["headers"]["X-Legal-Event"] == "entry.committed")
        assert committed["data"]["case_number"] == "1402778899"
    finally:
        sink.close()
        await hooks.delete_subscription(db_session, sub.id)


@pytest.mark.db
async def test_ci_events_fold_into_runs(db_session):
    import time

    from sqlalchemy import delete

    from app.db.models import CiEvent
    from scripts.replay_ci import status_bodies, synthesize

    # a fresh run number per test run: the cluster persists between runs
    number = 400_000 + int(time.time()) % 90_000
    events = synthesize(number, "v3", "abc1234def", fail_at="build")
    run_id = str(events[0]["payload"]["workflow_run"]["id"])
    try:
        for i, event in enumerate(events):
            assert await ci.record_github(db_session, delivery_id=event["delivery_id"], event=event["kind"],
                                          payload=event["payload"], source="replay")
            if i == 3:
                # the same moment reported through /ci/status (scripts/ci_status.sh shape)
                for report in status_bodies(event):
                    await ci.record_status(db_session, report, source="replay")
        # redelivery of the same id is ignored
        assert not await ci.record_github(db_session, delivery_id=events[0]["delivery_id"], event="workflow_run",
                                          payload=events[0]["payload"])
        await db_session.commit()

        runs = await ci.list_ci_runs(db_session, limit=5)
        run = next(r for r in runs if r["run_number"] == number)
        assert run["branch"] == "v3" and run["sha"] == "abc1234def"
        assert run["status"] == "completed" and run["conclusion"] == "failure"
        jobs = {j["name"]: j for j in run["jobs"]}
        assert jobs["test"]["conclusion"] == "success" and jobs["build"]["conclusion"] == "failure"
        assert "smoke" not in jobs  # the run stopped at build
        assert any(s["name"] == "Lint (ruff)" and s["status"] == "completed" for s in jobs["test"]["stages"])
    finally:
        await db_session.execute(delete(CiEvent).where(CiEvent.run_id == run_id))
        await db_session.commit()

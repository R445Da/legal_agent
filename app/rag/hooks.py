"""
Outbound webhooks through a transactional outbox.

`emit()` writes one `webhook_deliveries` row per matching subscription **in
the caller's transaction**, so a delivery exists if and only if the event it
reports was committed. `drain()` sends what is due — from whichever process
gets there first: the API runs it on a timer, the Streamlit app runs it right
after it emits — locking rows with `FOR UPDATE SKIP LOCKED` so the two never
send the same delivery twice. Failures back off (5 s · 2^attempts) and die
after six tries. Every request carries an HMAC-SHA256 signature of the body
under the subscription's own secret, plus the delivery id for deduplication.

Events: run.step, run.status, entry.committed, answer.created, ping.
"""

import asyncio
import datetime as dt
import hashlib
import hmac
import json
import os
import secrets
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import WebhookDelivery, WebhookSubscription

EVENTS = ("run.step", "run.status", "entry.committed", "answer.created", "ping")
_BACKOFF_BASE_S = 5
MAX_ATTEMPTS = 6
_TIMEOUT_S = 10.0
USER_AGENT = "legal-agent-webhooks/1"


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


# --------------------------------------------------------------------------- #
# Signing
# --------------------------------------------------------------------------- #
def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def verify(secret: str | None, body: bytes, header: str | None) -> bool:
    """Constant-time check of an `X-…-Signature-256` header against the body."""
    if not secret or not header:
        return False
    return hmac.compare_digest(sign(secret, body), header.strip())


def new_secret() -> str:
    return secrets.token_hex(32)


def allowed_url(url: str) -> bool:
    """http(s) only; and only the hosts in WEBHOOK_ALLOWED_HOSTS when it is set."""
    try:
        parts = urlparse(url)
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return False
    allowed = [h.strip().lower() for h in os.environ.get("WEBHOOK_ALLOWED_HOSTS", "").split(",") if h.strip()]
    return not allowed or parts.hostname.lower() in allowed


def matches(events: list | None, event: str) -> bool:
    for pattern in events or []:
        if pattern == "*" or pattern == event:
            return True
        if pattern.endswith("*") and event.startswith(pattern[:-1]):
            return True
    return False


# --------------------------------------------------------------------------- #
# Subscriptions
# --------------------------------------------------------------------------- #
def subscription_view(sub: WebhookSubscription, *, with_secret: bool = False) -> dict:
    out = {
        "id": str(sub.id), "url": sub.url, "events": list(sub.events or []), "active": bool(sub.active),
        "description": sub.description,
        "created_at": sub.created_at.isoformat() if sub.created_at else None,
    }
    if with_secret:
        out["secret"] = sub.secret
    return out


def delivery_view(d: WebhookDelivery) -> dict:
    return {
        "id": str(d.id), "subscription_id": str(d.subscription_id), "event": d.event,
        "status": d.status, "attempts": d.attempts, "response_code": d.response_code, "error": d.error,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "sent_at": d.sent_at.isoformat() if d.sent_at else None,
        "next_attempt_at": d.next_attempt_at.isoformat() if d.next_attempt_at else None,
        "payload": d.payload or {},
    }


async def create_subscription(
    session: AsyncSession, *, url: str, events: list[str] | None = None,
    description: str | None = None, secret: str | None = None,
) -> WebhookSubscription:
    if not allowed_url(url):
        raise ValueError("URL باید http(s) باشد" + (" و در فهرست میزبان‌های مجاز (WEBHOOK_ALLOWED_HOSTS)" if os.environ.get("WEBHOOK_ALLOWED_HOSTS") else ""))
    sub = WebhookSubscription(url=url, secret=secret or new_secret(), events=list(events or ["*"]),
                              description=description, active=True)
    session.add(sub)
    await session.commit()
    await session.refresh(sub)
    return sub


async def list_subscriptions(session: AsyncSession) -> list[WebhookSubscription]:
    return list((await session.execute(
        select(WebhookSubscription).order_by(WebhookSubscription.created_at.desc())
    )).scalars().all())


async def delete_subscription(session: AsyncSession, subscription_id) -> bool:
    sub = await session.get(WebhookSubscription, subscription_id)
    if sub is None:
        return False
    await session.delete(sub)
    await session.commit()
    return True


async def list_deliveries(
    session: AsyncSession, *, subscription_id=None, status: str | None = None, limit: int = 50,
) -> list[WebhookDelivery]:
    query = select(WebhookDelivery).order_by(WebhookDelivery.created_at.desc()).limit(limit)
    if subscription_id:
        query = query.where(WebhookDelivery.subscription_id == subscription_id)
    if status:
        query = query.where(WebhookDelivery.status == status)
    return list((await session.execute(query)).scalars().all())


# --------------------------------------------------------------------------- #
# Emit (no commit — joins the caller's transaction)
# --------------------------------------------------------------------------- #
async def emit(session: AsyncSession, event: str, data: dict | None = None) -> int:
    """Queue `event` for every active subscription that wants it. Returns how
    many deliveries were queued. Never commits: the caller does, so the
    delivery row and the fact it reports land together."""
    subs = (await session.execute(
        select(WebhookSubscription).where(WebhookSubscription.active.is_(True))
    )).scalars().all()
    n = 0
    now = _now()
    for sub in subs:
        if not matches(sub.events, event):
            continue
        session.add(WebhookDelivery(subscription_id=sub.id, event=event, payload=data or {},
                                    status="pending", attempts=0, next_attempt_at=now))
        n += 1
    return n


def envelope(delivery: WebhookDelivery) -> dict:
    return {
        "id": str(delivery.id), "event": delivery.event,
        "created_at": delivery.created_at.isoformat() if delivery.created_at else _now().isoformat(),
        "attempt": int(delivery.attempts or 0) + 1,
        "data": delivery.payload or {},
    }


# --------------------------------------------------------------------------- #
# Deliver + drain
# --------------------------------------------------------------------------- #
async def deliver(client, sub: WebhookSubscription, delivery: WebhookDelivery) -> tuple[int | None, str | None]:
    """POST one delivery. Returns (http status or None, error or None)."""
    if not allowed_url(sub.url):
        return None, "url not allowed"
    body = json.dumps(envelope(delivery), ensure_ascii=False).encode("utf-8")
    headers = {
        "content-type": "application/json",
        "user-agent": USER_AGENT,
        "X-Legal-Event": delivery.event,
        "X-Legal-Delivery": str(delivery.id),
        "X-Legal-Timestamp": _now().isoformat(timespec="seconds"),
        "X-Legal-Signature-256": sign(sub.secret, body),
    }
    try:
        response = await client.post(sub.url, content=body, headers=headers, timeout=_TIMEOUT_S)
    except Exception as error:  # noqa: BLE001 — recorded on the row, retried later
        return None, f"{type(error).__name__}: {error}"[:300]
    if 200 <= response.status_code < 300:
        return response.status_code, None
    return response.status_code, f"HTTP {response.status_code}: {response.text[:200]}"


async def drain(session_factory: async_sessionmaker, *, limit: int = 50) -> int:
    """Send every due delivery this process can lock. Returns how many it tried."""
    import httpx

    now = _now()
    async with session_factory() as session:
        rows = (await session.execute(
            select(WebhookDelivery)
            .where(WebhookDelivery.status.in_(("pending", "failed")), WebhookDelivery.next_attempt_at <= now)
            .order_by(WebhookDelivery.created_at).limit(limit)
            .with_for_update(skip_locked=True)
        )).scalars().all()
        if not rows:
            return 0
        sub_ids = {r.subscription_id for r in rows}
        subs = {s.id: s for s in (await session.execute(
            select(WebhookSubscription).where(WebhookSubscription.id.in_(sub_ids))
        )).scalars().all()}
        async with httpx.AsyncClient() as client:
            for delivery in rows:
                sub = subs.get(delivery.subscription_id)
                if sub is None or not sub.active:
                    delivery.status, delivery.error = "dead", "subscription inactive"
                    continue
                code, error = await deliver(client, sub, delivery)
                delivery.attempts = int(delivery.attempts or 0) + 1
                delivery.response_code = code
                if error is None:
                    delivery.status, delivery.error, delivery.sent_at = "sent", None, _now()
                else:
                    delivery.error = error
                    if delivery.attempts >= MAX_ATTEMPTS:
                        delivery.status = "dead"
                    else:
                        delivery.status = "failed"
                        delivery.next_attempt_at = _now() + dt.timedelta(
                            seconds=_BACKOFF_BASE_S * (2 ** (delivery.attempts - 1)))
        await session.commit()
        return len(rows)


_drain_pending = False


def drain_soon(session: AsyncSession, *, delay: float = 0.5) -> None:
    """Schedule one `drain()` on the current loop, debounced. Best effort:
    the API's timer catches anything this misses."""
    global _drain_pending
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if _drain_pending:
        return
    bind = session.bind
    if bind is None:
        return
    factory = async_sessionmaker(bind, expire_on_commit=False)
    _drain_pending = True

    async def _later() -> None:
        global _drain_pending
        try:
            await asyncio.sleep(delay)
            await drain(factory)
        except Exception:  # noqa: BLE001 — never let bookkeeping break the request
            pass
        finally:
            _drain_pending = False

    loop.create_task(_later())


async def notify(session: AsyncSession, event: str, data: dict | None = None) -> int:
    """`emit()` and, if anything was queued, a `drain_soon()` after the caller
    commits. For call sites that commit right after."""
    n = await emit(session, event, data)
    if n:
        drain_soon(session)
    return n

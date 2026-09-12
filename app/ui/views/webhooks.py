"""۱۹ وب‌هوک‌ها و CI — outbound subscriptions, the delivery log, inbound CI events."""

import streamlit as st

from app.ui import aio, components
from app.ui.resources import session
from app.ui.theme import esc, fa_num, kv, panel, stamp

_EVENT_FA = {
    "*": "همهٔ رویدادها", "run.step": "گام خط لوله", "run.status": "وضعیت اجرا",
    "entry.committed": "ثبت مدخل", "answer.created": "پاسخ ثبت‌شده", "ping": "آزمایش",
}
_STATUS_FA = {"sent": ("ارسال‌شده", "teal"), "pending": ("در صف", "gold"), "failed": ("ناموفق", "review"),
              "dead": ("متوقف", "red")}


async def _subs() -> list[dict]:
    from app.rag import hooks

    async with session() as s:
        return [hooks.subscription_view(x) for x in await hooks.list_subscriptions(s)]


async def _create(url: str, events: list[str], description: str) -> dict:
    from app.rag import hooks

    async with session() as s:
        sub = await hooks.create_subscription(s, url=url, events=events, description=description or None)
        return hooks.subscription_view(sub, with_secret=True)


async def _delete(sub_id: str) -> None:
    import uuid

    from app.rag import hooks

    async with session() as s:
        await hooks.delete_subscription(s, uuid.UUID(sub_id))


async def _ping(sub_id: str) -> dict:
    import uuid

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import WebhookDelivery
    from app.rag import hooks

    async with session() as s:
        delivery = WebhookDelivery(subscription_id=uuid.UUID(sub_id), event="ping",
                                   payload={"message": "سلام از آرشیو حقوقی"}, status="pending", attempts=0)
        s.add(delivery)
        await s.commit()
        delivery_id = delivery.id
        factory = async_sessionmaker(s.bind, expire_on_commit=False)
    await hooks.drain(factory)
    async with session() as s:
        return hooks.delivery_view(await s.get(WebhookDelivery, delivery_id))


async def _deliveries() -> list[dict]:
    from app.rag import hooks

    async with session() as s:
        return [hooks.delivery_view(d) for d in await hooks.list_deliveries(s, limit=30)]


async def _ci_runs() -> list[dict]:
    from app.rag import ci

    async with session() as s:
        return await ci.list_ci_runs(s, limit=8)


def render(cfg: dict, state: dict) -> None:
    st.title("وب‌هوک‌ها و CI")
    st.caption("رویدادهای آرشیو به بیرون (امضاشده)، رویدادهای CI به داخل.")

    out_col, in_col = st.columns([3, 2])

    with out_col:
        st.subheader("اشتراک‌های خروجی")
        with st.form("hook_new", clear_on_submit=True):
            url = st.text_input("نشانی گیرنده (URL)", placeholder="http://127.0.0.1:8099/hook")
            events = st.multiselect("رویدادها", list(_EVENT_FA), default=["*"], format_func=lambda k: _EVENT_FA[k])
            description = st.text_input("توضیح", placeholder="مثلاً: n8n / Slack / گیرندهٔ آزمایشی")
            if st.form_submit_button("ثبت اشتراک", type="primary"):
                try:
                    created = aio.run(_create(url.strip(), events or ["*"], description.strip()))
                    st.session_state["hook_secret_once"] = created
                except Exception as error:  # noqa: BLE001
                    components.error_box(error)
        shown = st.session_state.pop("hook_secret_once", None)
        if shown:
            st.success("اشتراک ثبت شد. این کلید فقط همین یک بار نشان داده می‌شود:")
            st.code(shown["secret"], language=None)
            st.caption("امضا: `X-Legal-Signature-256: sha256=HMAC(secret, body)` · شناسهٔ تحویل: `X-Legal-Delivery`")

        try:
            subs = aio.run(_subs())
        except Exception as error:  # noqa: BLE001
            components.error_box(error)
            subs = []
        if not subs:
            components.empty("هنوز اشتراکی ثبت نشده است. برای آزمایش: python -m scripts.hook_sink --port 8099")
        for sub in subs:
            with st.container(border=True):
                st.markdown(
                    f"<div class='kv'><span class='k mono' style='direction:ltr'>{esc(sub['url'])}</span>"
                    f"<span>{esc(sub.get('description') or '')}</span></div>"
                    + "".join(stamp(_EVENT_FA.get(e, e), "teal") for e in sub["events"]),
                    unsafe_allow_html=True,
                )
                c1, c2 = st.columns(2)
                if c1.button("ارسال آزمایشی", key=f"hook_ping_{sub['id']}", use_container_width=True):
                    try:
                        result = aio.run(_ping(sub["id"]))
                        label, _kind = _STATUS_FA.get(result["status"], (result["status"], "gray"))
                        (st.success if result["status"] == "sent" else st.warning)(
                            f"{label} — کد {result.get('response_code') or '—'} {result.get('error') or ''}"
                        )
                    except Exception as error:  # noqa: BLE001
                        components.error_box(error)
                if c2.button("حذف", key=f"hook_del_{sub['id']}", use_container_width=True):
                    aio.run(_delete(sub["id"]))
                    st.rerun()

        st.subheader("تحویل‌های اخیر")
        try:
            deliveries = aio.run(_deliveries())
        except Exception as error:  # noqa: BLE001
            components.error_box(error)
            deliveries = []
        if not deliveries:
            components.empty("تحویلی ثبت نشده است.")
        for d in deliveries:
            label, kind = _STATUS_FA.get(d["status"], (d["status"], "gray"))
            st.markdown(
                f"<div class='kv'><span class='k'>{stamp(label, kind)} {esc(d['event'])}</span>"
                f"<span class='meta mono'>{fa_num(d['attempts'])} تلاش · {esc(str(d.get('response_code') or ''))} "
                f"{esc((d.get('error') or '')[:80])}</span></div>",
                unsafe_allow_html=True,
            )

    with in_col:
        st.subheader("رویدادهای CI")
        try:
            runs = aio.run(_ci_runs())
        except Exception as error:  # noqa: BLE001
            components.error_box(error)
            runs = []
        components.ci_panel(runs, title="اجراهای اخیر", empty_hint="هنوز رویدادی نرسیده است.")
        for run in runs[:3]:
            for job in run.get("jobs") or []:
                stages = job.get("stages") or []
                if stages:
                    panel(
                        f"#{fa_num(run.get('run_number') or '')} · {esc(job['name'])}",
                        kv([(s["name"], f"{s.get('status') or ''} {s.get('conclusion') or ''}".strip()) for s in stages]),
                    )
        st.caption(
            "دریافت از GitHub: `POST /hooks/github` با `GITHUB_WEBHOOK_SECRET` · گزارش مرحله‌ای از خودِ گردش‌کار: "
            "`scripts/ci_status.sh` → `POST /ci/status` · بازپخش آفلاین: `python -m scripts.replay_ci`"
        )

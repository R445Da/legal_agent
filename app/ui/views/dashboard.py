"""۰۲ داشبورد — the state of the archive at a glance, in ledger form."""

import streamlit as st

from app.rag.catalog import COLLECTION_FA
from app.ui import aio, components
from app.ui.resources import session
from app.ui.theme import (
    case_id, chips, esc, fa_num, ledger, panel, stamp, timeline,
)


async def _ci_runs() -> list[dict]:
    from app.rag import ci

    async with session() as s:
        return await ci.list_ci_runs(s, limit=5)


async def _hook_counts() -> dict:
    from sqlalchemy import func, select

    from app.db.models import WebhookDelivery, WebhookSubscription

    async with session() as s:
        subs = await s.scalar(select(func.count()).select_from(WebhookSubscription)) or 0
        rows = (await s.execute(
            select(WebhookDelivery.status, func.count()).group_by(WebhookDelivery.status)
        )).all()
    return {"subscriptions": subs, **{status: n for status, n in rows}}


@st.fragment(run_every="3s")
def _live_ci() -> None:
    """Refreshes on its own every few seconds — the rest of the page does not."""
    try:
        runs = aio.run(_ci_runs())
        counts = aio.run(_hook_counts())
    except Exception as error:  # noqa: BLE001 — an old database without the v3 tables
        panel("خط لولهٔ CI", f"<div class='meta'>{esc(str(error)[:160])}</div>")
        return
    components.ci_panel(runs, empty_hint="هنوز رویدادی از CI نرسیده است — «python -m scripts.replay_ci» یک اجرا را بازپخش می‌کند.")
    bits = [f"{fa_num(counts.get('subscriptions', 0))} اشتراک"]
    for status, label in (("sent", "ارسال‌شده"), ("pending", "در صف"), ("failed", "ناموفق"), ("dead", "متوقف")):
        if counts.get(status):
            bits.append(f"{fa_num(counts[status])} {label}")
    st.caption("وب‌هوک‌ها: " + " · ".join(bits))


def render(cfg: dict, state: dict) -> None:
    st.title("داشبورد")
    st.caption("وضعیت آرشیو در یک نگاه")

    counts = state["counts"]
    cases = state["cases"]
    queue = state["review_queue"]
    archive = state.get("archive") or {}

    # The case archive in four numbers — the relational side of the same data.
    archive_cards = [
        ledger(archive.get("cases", 0), "پرونده‌ها (بایگانی)", accent="teal"),
        ledger(archive.get("laws", 0), "مواد قانونی", accent="gold"),
        ledger(archive.get("citations", 0), "استنادها"),
        ledger(archive.get("persons", 0) + archive.get("orgs", 0), "اشخاص و سازمان‌ها"),
    ]
    st.markdown(
        "<div style='display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:14px'>"
        + "".join(archive_cards) + "</div>",
        unsafe_allow_html=True,
    )

    cards = [
        ledger(len(cases), "پرونده‌ها", accent="teal"),
        ledger(counts["entries"], "مدخل‌های ساختاریافته"),
        ledger(counts["documents"], "اسناد خام", accent="gold"),
        ledger(counts["chunks"], "قطعات نمایه‌شده"),
        ledger(len(queue), "در صف بازبینی", accent="red" if queue else "teal"),
    ]
    st.markdown(
        "<div style='display:grid;grid-template-columns:repeat(5,1fr);gap:14px;margin-bottom:20px'>"
        + "".join(cards) + "</div>",
        unsafe_allow_html=True,
    )

    _live_ci()

    left, right = st.columns(2)

    with right:
        events = state["events"][:8]
        panel(
            "آخرین رویدادها",
            timeline([
                {
                    "date": e.get("date"),
                    "title": e.get("what") or e.get("type") or "—",
                    "detail": e.get("case_title"),
                }
                for e in events
            ]),
            sub=f"{fa_num(len(state['events']))} رویداد در کل",
        )

    with left:
        if queue:
            body = "".join(
                f"<div class='kv'><span class='k'>{case_id(c['number'])}</span>"
                f"<span>{esc(c['title'])}<div class='meta'>"
                + "".join(stamp(r, "review") for r in c["incomplete_reasons"])
                + "</div></span></div>"
                for c in queue[:6]
            )
            panel("صف بازبینی", body, sub=f"{fa_num(len(queue))} پرونده ناقص")
            if st.button("صف کامل", use_container_width=True):
                st.session_state["view"] = "review"
                st.rerun()
        else:
            panel("صف بازبینی", "<div class='meta'>همهٔ پرونده‌ها کامل‌اند.</div>")

        panel(
            "مجموعه‌ها",
            "".join(
                f"<div class='kv'><span class='k'>{esc(COLLECTION_FA.get(c['name'], c['name']))}</span>"
                f"<span class='mono'>{fa_num(c['documents'])}</span></div>"
                for c in state["collections"]
            ) or "<div class='meta'>—</div>",
        )

    panel(
        "پرتکرارترین برچسب‌ها",
        chips([f"{t['tag']} ({fa_num(t['cases'])})" for t in state["tags"][:24]], teal=True),
        sub=f"{fa_num(len(state['tags']))} برچسب یکتا",
    )

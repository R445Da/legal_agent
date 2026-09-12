"""۰۲ داشبورد — the state of the archive at a glance, in ledger form."""

import streamlit as st

from app.rag.catalog import COLLECTION_FA
from app.ui import components
from app.ui.theme import (
    case_id, chips, esc, fa_num, ledger, panel, stamp, timeline,
)


def render(cfg: dict, state: dict) -> None:
    st.title("داشبورد")
    st.caption("وضعیت آرشیو در یک نگاه")

    counts = state["counts"]
    cases = state["cases"]
    queue = state["review_queue"]

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

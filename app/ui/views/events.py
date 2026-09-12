"""۰۴ رویدادها — every event across every case, on one timeline."""

import streamlit as st

from app.ui import components
from app.ui.theme import fa_num


def render(cfg: dict, state: dict) -> None:
    st.title("رویدادها")
    st.caption("همهٔ رویدادهای استخراج‌شده از تمام پرونده‌ها، از جدید به قدیم.")

    events = state["events"]
    if not events:
        components.empty("رویدادی ثبت نشده است.")
        return

    query = st.text_input(
        "جستجو", key="ev_q", label_visibility="collapsed",
        placeholder="جستجو در رویدادها…",
    )
    if query:
        needle = query.strip()
        events = [
            e for e in events
            if needle in str(e.get("what") or "") or needle in str(e.get("detail") or "")
            or needle in str(e.get("case_title") or "")
        ]

    st.caption(f"{fa_num(len(events))} رویداد")

    components.rowlist_start()
    for index, event in enumerate(events[:200]):
        if components.row(
            event.get("what") or event.get("type") or "—",
            fa_num(event.get("date") or "—"),
            event.get("detail"),
            f"پرونده: {event.get('case_title')} · شماره {fa_num(event.get('case_number') or 'ندارد')}",
            key=f"ev_{index}_{event.get('entry_id')}",
        ):
            st.session_state["open_case"] = event["case_id"]
            st.session_state["view"] = "cases"
            st.rerun()

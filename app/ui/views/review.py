"""
۰۹ بازبینی انسانی — the queue of cases the extractor could not complete.

A case lands here when it has no case number or no parties. Fixing it means
editing the entry's extracted fields, which is what the form below writes back.
"""

import streamlit as st
from sqlalchemy import select

from app.db.models import Entry
from app.rag import catalog
from app.ui import aio, components, data
from app.ui.resources import session
from app.ui.theme import card, esc, fa_num


async def _patch_entry(entry_id: str, entities: dict, title: str) -> None:
    async with session() as s:
        entry = await s.get(Entry, entry_id)
        if entry is None:
            raise RuntimeError("مدخل پیدا نشد.")
        merged = dict(entry.entities or {})
        merged.update({k: v for k, v in entities.items() if v})
        entry.entities = merged
        if title:
            entry.title = title
        await s.commit()


async def _mark_reviewed(entry_id: str, verdict: str, note: str) -> None:
    async with session() as s:
        await catalog.add_label(
            s, kind="review", target_type="entry", target_id=entry_id,
            value=verdict, note=note or None, labeled_by="ui",
        )


def render(cfg: dict, state: dict) -> None:
    st.title("بازبینی انسانی")
    queue = state["review_queue"]
    st.caption(
        f"{fa_num(len(queue))} پرونده ناقص است. پرونده وقتی ناقص شمرده می‌شود که "
        "شمارهٔ پرونده یا طرفین از متن استخراج نشده باشد."
    )

    if not queue:
        components.empty("صف خالی است — همهٔ پرونده‌ها کامل‌اند.")
        return

    for case in queue:
        with st.expander(f"{case['title']} — {'، '.join(case['incomplete_reasons'])}"):
            card(
                f"<div class='meta'>{esc(case['text'][:400])}</div>",
                warn=True,
            )
            entry = case["entries"][0]
            entities = entry.get("entities") or {}

            form = st.columns(3)
            title = form[0].text_input("عنوان", value=entry.get("title") or "", key=f"rv_t_{entry['id']}")
            number = form[1].text_input(
                "شمارهٔ پرونده", value=entities.get("case_number") or "", key=f"rv_n_{entry['id']}"
            )
            court = form[2].text_input("مرجع", value=entities.get("court") or "", key=f"rv_c_{entry['id']}")

            more = st.columns(3)
            topic = more[0].text_input("موضوع", value=entities.get("topic") or "", key=f"rv_s_{entry['id']}")
            branch = more[1].text_input("شعبه", value=entities.get("branch") or "", key=f"rv_b_{entry['id']}")
            year = more[2].text_input("سال", value=entities.get("year") or "", key=f"rv_y_{entry['id']}")

            note = st.text_input("یادداشت بازبینی", key=f"rv_note_{entry['id']}")

            actions = st.columns(3)
            if actions[0].button("ذخیرهٔ اصلاحات", key=f"rv_save_{entry['id']}", type="primary", use_container_width=True):
                try:
                    aio.run(_patch_entry(entry["id"], {
                        "case_number": number, "court": court,
                        "topic": topic, "branch": branch, "year": year,
                    }, title))
                except Exception as error:  # noqa: BLE001
                    components.error_box(error)
                else:
                    data.refresh()
                    st.success("ذخیره شد.")
                    st.rerun()

            if actions[1].button("تایید بدون تغییر", key=f"rv_ok_{entry['id']}", use_container_width=True):
                aio.run(_mark_reviewed(entry["id"], "ok", note))
                st.success("به‌عنوان بازبینی‌شده ثبت شد.")

            if actions[2].button("علامت‌گذاری مشکل‌دار", key=f"rv_bad_{entry['id']}", use_container_width=True):
                aio.run(_mark_reviewed(entry["id"], "problem", note))
                st.warning("مشکل ثبت شد.")

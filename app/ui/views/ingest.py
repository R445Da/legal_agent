"""
۰۵ بایگانی سند جدید — the two-step archive flow from the original UI.

Paste or upload, press «استخراج و پیش‌نمایش», review the structured draft the
model produced, then «ثبت در آرشیو». Nothing is written before the confirm, so
a bad extraction costs nothing.
"""

import datetime as dt

import streamlit as st

from app.rag.orchestrator import commit_entry, extract_entry, find_related
from app.rag.ingest import ingest_document
from app.ui import aio, components, data
from app.ui.resources import session
from app.ui.theme import card, chips, esc, fa_num


async def _extract(llm, text: str) -> dict:
    async with session() as s:
        draft = await extract_entry(llm, text)
        related = await find_related(s, text)
        return {"draft": draft, "related": related}


async def _commit(draft: dict, text: str, source: str) -> str:
    async with session() as s:
        entry = await commit_entry(s, draft, text, source=source)
        await s.commit()
        return str(entry.id)


async def _plain_ingest(name: str, text: str, collection: str) -> str:
    async with session() as s:
        _doc, status = await ingest_document(
            s, text=text, source=name, title=name,
            metadata={"collection": collection}, replace=True,
        )
        await s.commit()
        return status


def _structured(cfg: dict) -> None:
    st.caption("متن جلسه را وارد کنید تا مدل مدخل ساختاریافته بسازد؛ پس از تایید شما ثبت می‌شود.")
    text = st.text_area("متن سند یا جلسه", key="ing_text", height=220)

    if st.button("استخراج و پیش‌نمایش", type="primary", disabled=not text.strip()):
        try:
            with st.spinner("در حال استخراج ساختاریافته…"):
                st.session_state["ing_result"] = aio.run(_extract(cfg["llm"], text))
                st.session_state["ing_text_snapshot"] = text
        except Exception as error:  # noqa: BLE001
            components.error_box(error)
            return

    result = st.session_state.get("ing_result")
    if not result:
        return

    st.divider()
    draft = result["draft"]
    card(
        f"<h4>{esc(draft.get('title') or 'بدون عنوان')}</h4>"
        f"<div class='meta'>{esc(draft.get('summary') or '')}</div>"
        + "<div style='margin-top:8px'>" + chips(draft.get("tags") or [], teal=True) + "</div>"
    )

    edited = st.data_editor(
        [{"فیلد": k, "مقدار": ("" if v is None else str(v))} for k, v in draft.items()],
        use_container_width=True, hide_index=True, key="ing_editor",
    )

    if result.get("related"):
        with st.expander(f"مدخل‌های مرتبط ({fa_num(len(result['related']))})"):
            st.json(result["related"])

    source = st.text_input(
        "شناسهٔ منبع", key="ing_source",
        value=f"ui/{dt.datetime.now():%Y%m%d-%H%M%S}",
    )

    # Right to left: the first column is the rightmost, so the primary
    # action sits on the right where the eye lands first.
    confirm, cancel = st.columns(2)
    if confirm.button("ثبت در آرشیو", type="primary", use_container_width=True):
        merged = {**draft}
        for row in edited:
            if row["فیلد"] in merged and isinstance(merged[row["فیلد"]], str):
                merged[row["فیلد"]] = row["مقدار"]
        try:
            with st.spinner("در حال ثبت و نمایه‌سازی…"):
                entry_id = aio.run(_commit(merged, st.session_state["ing_text_snapshot"], source))
        except Exception as error:  # noqa: BLE001
            components.error_box(error)
            return
        st.session_state.pop("ing_result", None)
        data.refresh()
        st.success(f"ثبت شد — شناسهٔ مدخل {esc(entry_id)}")

    if cancel.button("انصراف", use_container_width=True):
        st.session_state.pop("ing_result", None)
        st.rerun()


def _files(state: dict) -> None:
    st.caption("بارگذاری مستقیم فایل متنی — بدون استخراج ساختاریافته، فقط نمایه‌سازی برای جستجو.")
    names = [c["name"] for c in state["collections"]] or ["uploads"]
    collection = st.selectbox("مجموعهٔ مقصد", names + ["uploads"], key="ing_coll")
    files = st.file_uploader("فایل‌ها", type=["txt", "md"], accept_multiple_files=True, key="ing_files")

    if files and st.button("بایگانی فایل‌ها", type="primary"):
        for uploaded in files:
            try:
                body = uploaded.getvalue().decode("utf-8", errors="replace")
                status = aio.run(_plain_ingest(uploaded.name, body, collection))
                st.success(f"{uploaded.name} — {status}")
            except Exception as error:  # noqa: BLE001
                components.error_box(error)
        data.refresh()


def render(cfg: dict, state: dict) -> None:
    st.title("بایگانی سند جدید")
    structured, files = st.tabs(["استخراج ساختاریافته", "بارگذاری فایل"])
    with structured:
        _structured(cfg)
    with files:
        _files(state)

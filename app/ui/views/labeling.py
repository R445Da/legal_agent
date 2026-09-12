"""
۱۰ برچسب‌گذاری و بازخورد — human judgments that feed evaluation.

Run a query, mark each retrieved chunk relevant or not, and the labels
accumulate into an eval set. This is the highest-leverage screen in the system:
the playbook's point is that twenty to fifty real judgments are worth more than
any model swap, because without them you are tuning blind.
"""

import streamlit as st

from app.rag import catalog
from app.rag.retriever import retrieve_scored
from app.ui import aio, components
from app.ui.resources import session
from app.ui.theme import card, esc, fa_num


async def _retrieve(query: str, top_k: int, retrieval: dict):
    async with session() as s:
        return await retrieve_scored(s, query, top_k=top_k, **retrieval)


async def _label(kind, target_type, target_id, value, query, note=None):
    async with session() as s:
        return await catalog.add_label(
            s, kind=kind, target_type=target_type, target_id=target_id,
            value=value, query=query, note=note, labeled_by="ui",
        )


async def _labels(kind: str | None = None):
    async with session() as s:
        return await catalog.list_labels(s, kind=kind, limit=300)


async def _drop(label_id: str):
    async with session() as s:
        return await catalog.delete_label(s, label_id)


def _judge_tab(cfg: dict) -> None:
    query = st.text_input("پرسش برای داوری", key="lab_query")
    if st.button("بازیابی و داوری", type="primary", disabled=not query.strip()):
        try:
            with st.spinner("در حال بازیابی…"):
                st.session_state["lab_rows"] = [
                    {
                        "chunk_id": str(chunk.id),
                        "title": chunk.document.title or chunk.document.source,
                        "source": chunk.document.source,
                        "text": chunk.text,
                        "score": round(1 - distance, 3),
                    }
                    for chunk, distance in aio.run(_retrieve(query, cfg["top_k"], cfg["retrieval"]))
                ]
                st.session_state["lab_query_snapshot"] = query
        except Exception as error:  # noqa: BLE001
            components.error_box(error)
            return

    rows = st.session_state.get("lab_rows") or []
    if not rows:
        return

    st.caption(f"پرسش: **{st.session_state.get('lab_query_snapshot')}** — "
               f"{fa_num(len(rows))} قطعه برای داوری")

    for index, row in enumerate(rows, start=1):
        body = st.columns([6, 1, 1])
        with body[0]:
            card(
                f"<h4>[{fa_num(index)}] {esc(row['title'])}  ·  {fa_num(row['score'])}</h4>"
                f"<div class='meta'>{esc(row['source'])}</div>"
                f"<div style='margin-top:6px;line-height:2'>{esc(row['text'][:400])}</div>"
            )
        if body[1].button("مرتبط ✓", key=f"rel_{row['chunk_id']}", use_container_width=True):
            aio.run(_label("relevance", "chunk", row["chunk_id"], "1",
                           st.session_state["lab_query_snapshot"]))
            st.success("ثبت شد.")
        if body[2].button("نامرتبط ✗", key=f"irr_{row['chunk_id']}", use_container_width=True):
            aio.run(_label("relevance", "chunk", row["chunk_id"], "0",
                           st.session_state["lab_query_snapshot"]))
            st.info("ثبت شد.")


def _history_tab() -> None:
    kind = st.selectbox(
        "نوع", ["همه", "relevance", "tag", "review"], key="lab_kind",
        format_func=lambda k: {"همه": "همه", "relevance": "ارتباط", "tag": "برچسب",
                               "review": "بازبینی"}.get(k, k),
    )
    try:
        rows = aio.run(_labels(None if kind == "همه" else kind))
    except Exception as error:  # noqa: BLE001
        components.error_box(error)
        return

    if not rows:
        components.empty("هنوز داوری‌ای ثبت نشده است.")
        return

    positives = sum(1 for r in rows if r["kind"] == "relevance" and r["value"] == "1")
    negatives = sum(1 for r in rows if r["kind"] == "relevance" and r["value"] == "0")
    queries = {r["query"] for r in rows if r["query"]}
    cols = st.columns(4)
    cols[0].metric("کل داوری‌ها", fa_num(len(rows)))
    cols[1].metric("مرتبط", fa_num(positives))
    cols[2].metric("نامرتبط", fa_num(negatives))
    cols[3].metric("پرسش‌های یکتا", fa_num(len(queries)))

    st.dataframe(rows, use_container_width=True, hide_index=True)

    label_id = st.text_input("حذف داوری با شناسه", key="lab_del")
    if st.button("حذف", disabled=not label_id):
        if aio.run(_drop(label_id)):
            st.success("حذف شد.")
            st.rerun()
        else:
            st.warning("چنین داوری‌ای یافت نشد.")


def render(cfg: dict, state: dict) -> None:
    st.title("برچسب‌گذاری و بازخورد")
    st.caption(
        "داوری انسانی دربارهٔ اینکه هر قطعه واقعاً به پرسش مربوط است یا نه — "
        "همان چیزی که مجموعهٔ ارزیابی از آن ساخته می‌شود."
    )
    judge, history = st.tabs(["داوری نتایج", "داوری‌های ثبت‌شده"])
    with judge:
        _judge_tab(cfg)
    with history:
        _history_tab()

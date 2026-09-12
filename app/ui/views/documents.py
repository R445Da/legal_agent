"""۰۷ تیکت‌ها (اسناد) — the document archive, browsable and openable.

Every row opens in place: full text, or the chunks exactly as the retriever
stored them. That click-through is the point of this screen — a document you
can only see the title of is not an archive.
"""

import streamlit as st
from sqlalchemy import delete as sql_delete

from app.db.models import Document
from app.rag import catalog
from app.rag.ingest import get_document, list_documents
from app.ui import aio, components, data
from app.ui.resources import session
from app.ui.theme import card, chips, esc, fa_num, kv

_PAGE = 20


async def _page(query, filters, collection, offset):
    async with session() as s:
        meta = dict(filters or {})
        if collection:
            meta["collection"] = collection
        return await list_documents(
            s, q=query or None, limit=_PAGE, offset=offset, meta_filters=meta or None
        )


async def _detail(document_id: str):
    async with session() as s:
        return await get_document(s, document_id)


async def _delete(document_id: str):
    async with session() as s:
        await s.execute(sql_delete(Document).where(Document.id == document_id))
        await s.commit()


def _open_document(document_id: str) -> None:
    """The detail pane: metadata, then full text or chunks."""
    try:
        doc = aio.run(_detail(document_id))
    except Exception as error:  # noqa: BLE001
        components.error_box(error)
        return
    if not doc:
        st.warning("سند پیدا نشد.")
        return

    if st.button("→ بازگشت به فهرست", key="doc_back"):
        st.session_state["open_doc"] = None
        st.rerun()

    meta = doc.get("doc_metadata") or {}
    card(
        f"<h4>{esc(doc.get('title') or doc.get('source'))}</h4>"
        f"<div class='meta'>{esc(doc.get('source'))}</div>"
        + kv([
            ("مجموعه", catalog.COLLECTION_FA.get(meta.get("collection"), meta.get("collection") or "—")),
            ("تاریخ ثبت", fa_num((doc.get("created_at") or "—")[:10])),
            ("تعداد قطعات", fa_num(len(doc.get("chunks") or []))),
        ])
        + "<div style='margin-top:8px'>" + chips(
            [f"{k}: {v}" for k, v in meta.items() if k != "collection" and v]
        ) + "</div>"
    )

    full_tab, chunk_tab = st.tabs(["متن کامل", f"قطعات ({fa_num(len(doc.get('chunks') or []))})"])
    with full_tab:
        st.markdown(
            f"<div class='card' style='white-space:pre-wrap;line-height:2'>"
            f"{esc(doc.get('raw_text') or '—')}</div>",
            unsafe_allow_html=True,
        )
    with chunk_tab:
        for chunk in doc.get("chunks") or []:
            with st.expander(f"قطعهٔ {fa_num(chunk['chunk_index'] + 1)}"):
                st.markdown(
                    f"<div style='white-space:pre-wrap;line-height:2'>{esc(chunk['text'])}</div>",
                    unsafe_allow_html=True,
                )

    st.divider()
    if st.button("حذف این سند", key="doc_del", type="secondary"):
        aio.run(_delete(document_id))
        data.refresh()
        st.session_state["open_doc"] = None
        st.success("سند حذف شد.")
        st.rerun()


def render(cfg: dict, state: dict) -> None:
    st.title("تیکت‌ها (اسناد)")

    if st.session_state.get("open_doc"):
        _open_document(st.session_state["open_doc"])
        return

    st.caption("هر سند خام آرشیو. روی هر سند بزنید تا متن کامل و قطعاتش باز شود.")

    # One full-width search, flush with the rows beneath it. The facet
    # dropdowns used to be stacked inside a narrow third column, which is what
    # made this screen look cluttered — they fold away instead.
    query = st.text_input(
        "جستجو", key="doc_q", label_visibility="collapsed",
        placeholder="جستجو در عنوان، منبع یا شمارهٔ پرونده…",
    )

    collections = {c["name"]: c["documents"] for c in state["collections"]}
    filters: dict = {}
    active_facets = {k: v for k, v in (state["facets"] or {}).items() if v}

    with st.expander("صافی‌ها" + (f" ({fa_num(len(active_facets) + 1)})" if active_facets else "")):
        picks = st.columns(min(len(active_facets) + 1, 4))
        collection = picks[0].selectbox(
            "مجموعه", ["همه"] + list(collections), key="doc_coll",
            format_func=lambda n: "همه مجموعه‌ها" if n == "همه"
            else f"{catalog.COLLECTION_FA.get(n, n)} ({fa_num(collections[n])})",
        )
        collection = None if collection == "همه" else collection

        for index, (key, values) in enumerate(active_facets.items(), start=1):
            counts = {v["value"]: v["documents"] for v in values}
            picked = picks[index % len(picks)].selectbox(
                catalog.FACET_FA.get(key, key), ["همه"] + list(counts), key=f"doc_f_{key}",
                format_func=lambda v, c=counts: "همه" if v == "همه" else f"{v} ({fa_num(c[v])})",
            )
            if picked != "همه":
                filters[key] = picked

    offset = st.session_state.setdefault("doc_offset", 0)

    try:
        page = aio.run(_page(query, filters, collection, offset))
    except Exception as error:  # noqa: BLE001
        components.error_box(error)
        return

    total = page.get("total", 0)
    items = page.get("items", [])
    st.caption(f"{fa_num(total)} سند · نمایش {fa_num(offset + 1)} تا {fa_num(min(offset + _PAGE, total))}")

    components.rowlist_start()
    for item in items:
        meta = item.get("doc_metadata") or item.get("metadata") or {}
        collection = catalog.COLLECTION_FA.get(meta.get("collection"), meta.get("collection"))
        facts = " · ".join(f"{k}: {v}" for k, v in meta.items() if k != "collection" and v)
        if components.row(
            item.get("title") or item.get("source"),
            item.get("source"),
            (collection + (" · " + facts if facts else "")) if collection else facts or None,
            key=f"open_{item['id']}",
        ):
            st.session_state["open_doc"] = item["id"]
            st.rerun()

    nav = st.columns([1, 1, 4])
    if nav[0].button("→ قبلی", disabled=offset == 0, key="doc_prev"):
        st.session_state["doc_offset"] = max(0, offset - _PAGE)
        st.rerun()
    if nav[1].button("بعدی ←", disabled=offset + _PAGE >= total, key="doc_next"):
        st.session_state["doc_offset"] = offset + _PAGE
        st.rerun()

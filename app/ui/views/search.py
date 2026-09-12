"""
۰۶ جستجو و پرسش — grounded answers, raw retrieval, and the retrieval lab.

Three things on one screen, as in the original: ask a question and get a cited
answer; run retrieval alone to see exactly what the index returns; and compare
the pipeline with and without the reranker, which is where this system's latency
actually lives.
"""

import streamlit as st

from app.rag import catalog
from app.rag.pipeline import answer_question
from app.rag.retriever import effective_config, retrieve_scored
from app.ui import aio, components
from app.ui.resources import session
from app.ui.theme import card, esc, fa_ms, fa_num


def _scope_controls(state: dict, prefix: str) -> tuple[str | None, dict]:
    """Scope and facets, folded away so the query box owns the full width."""
    with st.expander("دامنه و صافی‌ها"):
        return _scope_body(state, prefix)


def _scope_body(state: dict, prefix: str) -> tuple[str | None, dict]:
    names = [c["name"] for c in state["collections"]]
    controls = [("collection", names)]
    controls.extend((key, values) for key, values in (state["facets"] or {}).items() if values)
    cols = st.columns(2)

    with cols[0]:
        collection = st.selectbox(
            "دامنه", ["همه مجموعه‌ها"] + names, key=f"{prefix}_coll",
            format_func=lambda n: n if n == "همه مجموعه‌ها" else catalog.COLLECTION_FA.get(n, n),
        )
    collection = None if collection == "همه مجموعه‌ها" else collection

    filters = {}
    for index, (key, values) in enumerate(controls[1:], start=1):
        with cols[index % len(cols)]:
            picked = st.selectbox(
                catalog.FACET_FA.get(key, key), ["همه"] + [v["value"] for v in values],
                key=f"{prefix}_{key}",
            )
            if picked != "همه":
                filters[key] = picked
    return collection, filters


def _latency(trace: dict, generate_ms: float | None) -> None:
    cols = st.columns(4)
    cols[0].metric("جستجوی برداری", fa_ms(trace.get("vector_ms")))
    cols[1].metric("جستجوی متنی", fa_ms(trace.get("lexical_ms")))
    cols[2].metric("بازرتبه‌بندی", fa_ms(trace.get("rerank_ms")),
                   help=f"{fa_num(trace.get('pairs_scored', 0))} جفت امتیازدهی شد")
    cols[3].metric("تولید پاسخ", fa_ms(generate_ms))


def _hits(rows) -> None:
    if not rows:
        components.empty("نتیجه‌ای یافت نشد.")
        return
    for index, (chunk, distance) in enumerate(rows, start=1):
        title = chunk.document.title or chunk.document.source
        with st.expander(f"[{fa_num(index)}] {title}  ·  {fa_num(f'{1-distance:.3f}')}"):
            st.caption(chunk.document.source)
            st.markdown(
                f"<div style='white-space:pre-wrap;line-height:2'>{esc(chunk.text)}</div>",
                unsafe_allow_html=True,
            )


def _ask_tab(cfg: dict, state: dict) -> None:
    question = st.text_area(
        "پرسش", key="ask_q", height=110, label_visibility="collapsed",
        placeholder="پرسش خود را بنویسید — مثلاً: در پرونده کالای معیوب دادگاه چه تصمیمی گرفت؟",
    )
    collection, filters = _scope_controls(state, "ask")

    if not st.button("پرسش با پاسخ مستند", type="primary", disabled=not question.strip()):
        return

    async def _run():
        async with session() as s:
            return await answer_question(
                s, cfg["llm"], question, top_k=cfg["top_k"],
                collection=collection, filters=filters or None,
                retrieval=cfg["retrieval"], max_tokens=cfg["max_tokens"], **cfg["knobs"],
            )

    try:
        with st.spinner("در حال بازیابی و تولید پاسخ…"):
            result = aio.run(_run())
    except Exception as error:  # noqa: BLE001
        components.error_box(error)
        return

    _latency(result.retrieval, result.latency_ms)
    components.reasoning_panel(result.reasoning)
    card(f"<div style='line-height:2'>{esc(result.answer)}</div>")
    components.usage_caption(model=result.model, input_tokens=result.input_tokens,
                             output_tokens=result.output_tokens)
    components.steps_panel(result.steps, title="مراحل پردازش")
    st.subheader("مستندات پاسخ")
    components.citations(result.contexts)


def _search_tab(cfg: dict, state: dict) -> None:
    st.caption("فقط بازیابی — بدون مدل زبانی. دقیقاً همان چیزی که نمایه برمی‌گرداند.")
    query = st.text_input(
        "عبارت جستجو", key="srch_q", label_visibility="collapsed",
        placeholder="عبارت جستجو — مثلاً: چک برگشتی بانک ملت",
    )
    collection, filters = _scope_controls(state, "srch")

    if not st.button("اجرا", type="primary", disabled=not query.strip()):
        return

    async def _run(retrieval):
        trace = {}
        async with session() as s:
            rows = await retrieve_scored(
                s, query, top_k=cfg["top_k"], collection=collection,
                filters=filters or None, trace=trace, **retrieval,
            )
        return rows, trace

    try:
        with st.spinner("در حال بازیابی…"):
            rows, trace = aio.run(_run(cfg["retrieval"]))
    except Exception as error:  # noqa: BLE001
        components.error_box(error)
        return

    _latency(trace, None)
    with st.expander("پیکربندی مؤثر بازیابی"):
        st.json(effective_config(hybrid=cfg["retrieval"]["hybrid"], rerank=cfg["retrieval"]["rerank"]))
    _hits(rows)


def _lab_tab(cfg: dict, state: dict) -> None:
    st.caption(
        "همان پرسش را با و بدون بازرتبه‌بندی اجرا می‌کند. بازرتبه‌بندی بزرگ‌ترین "
        "اهرم دقت است و در عین حال بیشترین هزینهٔ زمانی را دارد."
    )
    query = st.text_input(
        "عبارت جستجو", key="lab_q", label_visibility="collapsed",
        placeholder="عبارت جستجو برای مقایسه",
    )
    if not st.button("مقایسه", type="primary", disabled=not query.strip()):
        return

    async def _run(retrieval):
        trace = {}
        async with session() as s:
            rows = await retrieve_scored(s, query, top_k=cfg["top_k"], trace=trace, **retrieval)
        return rows, trace

    columns = st.columns(2)
    for column, on in zip(columns, (False, True)):
        with column:
            st.subheader("با بازرتبه‌بندی" if on else "بدون بازرتبه‌بندی")
            try:
                with st.spinner("در حال اجرا…"):
                    rows, trace = aio.run(_run({**cfg["retrieval"], "rerank": on}))
            except Exception as error:  # noqa: BLE001
                components.error_box(error)
                continue
            total = sum(trace.get(k, 0.0) for k in ("vector_ms", "lexical_ms", "rerank_ms"))
            st.metric("زمان کل بازیابی", fa_ms(total))
            _hits(rows)


def render(cfg: dict, state: dict) -> None:
    st.title("جستجو و پرسش")
    ask, search, lab = st.tabs(["پرسش با پاسخ مستند", "جستجوی متن", "آزمایشگاه بازیابی"])
    with ask:
        _ask_tab(cfg, state)
    with search:
        _search_tab(cfg, state)
    with lab:
        _lab_tab(cfg, state)

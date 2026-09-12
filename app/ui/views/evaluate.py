"""
Eval — score the retriever against `eval/*.jsonl`.

This is the page that turns a sidebar knob into evidence. The playbook's loop is:
note the baseline, change one thing, re-run, compare. The sweep button does that
automatically for the reranker, which is the setting with the largest effect on
both quality and latency.
"""

import pathlib

import streamlit as st

from app.rag.evaluate import load_cases, run_eval
from app.ui import aio, components
from app.ui.theme import fa_num
from app.ui.resources import session

EVAL_DIR = pathlib.Path("eval")


def _metrics_row(metrics: dict) -> None:
    keys = [k for k in ("hit@1", "hit@3", "hit@k", "mrr", "cov@k") if k in metrics]
    columns = st.columns(len(keys) or 1)
    for column, key in zip(columns, keys):
        column.metric(key, f"{metrics[key]:.2f}")


def render(cfg: dict, state: dict) -> None:
    st.title("ارزیابی بازیابی")
    st.caption(
        "فقط سنجهٔ بازیابی. hit@k و MRR می‌گویند اسناد مورد انتظار پیدا شدند و چه رتبه‌ای گرفتند — کیفیت پاسخ سنجیده نمی‌شود."
    )

    files = sorted(EVAL_DIR.glob("*.jsonl"))
    if not files:
        st.warning(f"مجموعهٔ ارزیابی در {EVAL_DIR}/ پیدا نشد.")
        return

    chosen = st.selectbox("مجموعهٔ ارزیابی", files, format_func=lambda p: p.name, key="eval_file")
    cases = load_cases(chosen)
    st.caption(fa_num(len(cases)) + " پرسش")

    run, sweep = st.columns(2)
    go = run.button("اجرای ارزیابی", type="primary")
    do_sweep = sweep.button(
        "جاروب بازرتبه‌بندی",
        help="مجموعه را سه‌بار اجرا می‌کند — بدون بازرتبه‌بندی، با آن، و با نصف عمق — تا هزینهٔ بازرتبه‌بندی در برابر امتیازی که می‌خرد سنجیده شود.",
    )

    async def _once(retrieval: dict) -> dict:
        async with session() as s:
            return await run_eval(s, cases, top_k=cfg["top_k"], retrieval=retrieval)

    if go:
        try:
            with st.spinner("در حال امتیازدهی…"):
                result = aio.run(_once(cfg["retrieval"]))
        except Exception as error:  # noqa: BLE001
            components.error_box(error)
            return
        _metrics_row(result.get("metrics", {}))
        with st.expander("جزئیات هر پرسش"):
            st.dataframe(result.get("rows", []), use_container_width=True, hide_index=True)

    if do_sweep:
        variants = [
            ("بدون بازرتبه‌بندی", {**cfg["retrieval"], "rerank": False}),
            ("با بازرتبه‌بندی", {**cfg["retrieval"], "rerank": True}),
            ("بازرتبه‌بندی با نصف عمق", {**cfg["retrieval"], "rerank": True,
                                        "rerank_top": max(3, cfg["retrieval"]["rerank_top"] // 2)}),
        ]
        table = []
        progress = st.progress(0.0)
        for i, (label, retrieval) in enumerate(variants, start=1):
            try:
                result = aio.run(_once(retrieval))
            except Exception as error:  # noqa: BLE001
                components.error_box(error)
                break
            table.append({"variant": label, **result.get("metrics", {})})
            progress.progress(i / len(variants))
        progress.empty()
        st.dataframe(table, use_container_width=True, hide_index=True)
        st.caption(
            "این امتیازها را کنار زمان‌های صفحهٔ «جستجو و پرسش» بگذارید — هزینهٔ "
            "بازرتبه‌بندی با تعداد نامزدهایی که می‌خواند خطی رشد می‌کند."
        )

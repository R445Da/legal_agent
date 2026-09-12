"""Bench — the same questions through several models, side by side."""

import streamlit as st

from app.rag.bench import NothingIndexed, run_bench
from app.ui import aio, components
from app.ui.theme import fa_ms, fa_num
from app.ui.sidebar import _catalog
from app.ui.resources import session

_DEFAULT_QUESTIONS = "در پرونده کالای معیوب دادگاه چه تصمیمی گرفت؟"


def render(cfg: dict, state: dict) -> None:
    st.title("مقایسهٔ مدل‌ها")
    st.caption(
        "بازیابی برای هر پرسش یک‌بار اجرا و همان پرسمان بین همهٔ مدل‌ها بازاستفاده می‌شود؛ "
        "پس این جدول فقط مرحلهٔ تولید پاسخ را مقایسه می‌کند."
    )

    by_id = {e["id"]: e for e in _catalog(False) if e["available"]}
    chosen = st.multiselect(
        "مدل‌ها", list(by_id), format_func=lambda i: by_id[i]["label"], max_selections=8,
        default=[cfg["model_id"]] if cfg["model_id"] in by_id else [],
        key="bench_models",
    )
    raw = st.text_area("پرسش‌ها (هر خط یک پرسش)", value=_DEFAULT_QUESTIONS, height=120, key="bench_qs")
    questions = [line for line in raw.splitlines() if line.strip()]

    if not st.button("اجرای مقایسه", type="primary", disabled=not (chosen and questions)):
        return

    async def _run():
        async with session() as s:
            return await run_bench(
                s, questions, chosen,
                top_k=cfg["top_k"], max_tokens=cfg["max_tokens"],
                retrieval=cfg["retrieval"], **cfg["knobs"],
            )

    try:
        with st.spinner(f"{fa_num(len(questions))} پرسش × {fa_num(len(chosen))} مدل…"):
            result = aio.run(_run())
    except NothingIndexed:
        st.warning("هنوز چیزی نمایه نشده — ابتدا از «بایگانی سند جدید» سند اضافه کنید.")
        return
    except Exception as error:  # noqa: BLE001
        components.error_box(error)
        return

    st.subheader("خلاصه")
    st.dataframe(result["summary"], use_container_width=True, hide_index=True)

    for row in result["rows"]:
        st.divider()
        st.markdown(f"**{row['question']}**")
        columns = st.columns(len(row["cells"]))
        for column, cell in zip(columns, row["cells"]):
            with column:
                st.caption(cell["model_id"])
                if cell.get("error"):
                    st.error(cell["error"])
                    continue
                latency = cell.get("latency_ms")
                st.caption(f"{fa_ms(latency)} · {fa_num(cell.get('output_tokens', '—'))} توکن")
                components.reasoning_panel(cell.get("reasoning"))
                st.write(cell.get("answer", ""))
        with st.expander("قطعه‌های مشترک این پاسخ‌ها"):
            st.dataframe(row["contexts"], use_container_width=True, hide_index=True)

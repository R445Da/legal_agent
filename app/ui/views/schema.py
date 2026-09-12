"""۱۲ ساختار داده و خط لوله — what the system stores, and how a request flows."""

import streamlit as st

from app.rag.retriever import effective_config
from app.ui import components
from app.ui.theme import card, chips, esc, fa_num

_FLOW_FA = {
    "query": "پرسش",
    "archive": "بایگانی",
    "analytics": "آمار",
}


def render(cfg: dict, state: dict) -> None:
    st.title("ساختار داده و خط لوله")

    schema = state.get("schema") or {}

    st.subheader("مدل داده")
    for model in schema.get("model", []):
        card(
            f"<h4>{esc(model['fa'])} <span class='meta'>({esc(model['name'])})</span> — "
            f"{fa_num(model['count'])}</h4>"
            f"<div class='meta'>{esc(model['what'])}</div>"
            "<div style='margin-top:8px'>" + chips(model["fields"]) + "</div>"
        )

    st.divider()
    st.subheader("خط لوله")
    for flow, steps in (schema.get("pipeline") or {}).items():
        st.markdown(f"**{_FLOW_FA.get(flow, flow)}**")
        card(
            "<div class='tl'>"
            + "".join(
                f"<div class='ev'><div>{fa_num(i)}. {esc(step)}</div></div>"
                for i, step in enumerate(steps, start=1)
            )
            + "</div>"
        )
    if schema.get("pipeline_note"):
        st.caption(schema["pipeline_note"])

    st.divider()
    st.subheader("پیکربندی مؤثر بازیابی")
    st.caption("آنچه هم‌اکنون واقعاً اجرا می‌شود — با احتساب تنظیمات نوار کناری.")
    st.json(effective_config(hybrid=cfg["retrieval"]["hybrid"], rerank=cfg["retrieval"]["rerank"]))

    st.subheader("مدل فعال و کلیدهای تنظیم")
    entry = cfg["entry"]
    card(
        f"<h4>{esc(entry['label'])}</h4>"
        f"<div class='meta'>شناسه: {esc(entry['id'])} · "
        f"{'مدل استدلالی' if entry['reasoning'] else 'مدل گفتگوی ساده'}</div>"
        "<div style='margin-top:8px'>"
        + chips([k["label"] for k in entry["knobs"]], teal=True)
        + "</div>"
    )

    st.divider()
    st.subheader("فرم مدخل ساختاریافته")
    entry_form = schema.get("entry_form") or {}
    if entry_form.get("fields"):
        st.dataframe(entry_form["fields"], use_container_width=True, hide_index=True)
    else:
        components.empty("ساختار مدخل در دسترس نیست.")

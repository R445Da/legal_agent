"""
آرشیو حقوقی — Legal RAG.

The interface. It replaces `app/static/app.html` and carries the same numbered
Persian sections, right to left, in light or dark, on the ledger design ported
in `app/ui/theme.py`.

Two collapsible panels, nothing across the top:

    [ model + retrieval ]   [ content ]   [ ۰۱..۱۴ sections ]
           left                                  right

Both are columns with the same chevron, not `st.sidebar`. Streamlit's sidebar
control vanishes from the DOM once collapsed and there is no API to reopen it
from Python, which left the panel permanently unreachable; and there is only one
sidebar anyway, while this layout needs two panels that behave identically.

It imports the engine directly (`app/rag`, `app/llm`, `app/db`), so the FastAPI
server does not need to be running.

    .venv/bin/streamlit run streamlit_app.py
"""

import streamlit as st

from app.ui import data, nav, resources, sidebar, theme
from app.ui.views import (
    agent, analytics, bench, cases, dashboard, documents, editor, entities,
    evaluate, events, ingest, labeling, laws, review, schema, search, taxonomy,
    webhooks,
)

st.set_page_config(
    page_title="آرشیو حقوقی",
    page_icon=":material/gavel:",
    layout="wide",
    initial_sidebar_state="expanded",
)

VIEWS = {
    "agent": agent, "dashboard": dashboard, "cases": cases, "events": events,
    "ingest": ingest, "search": search, "documents": documents,
    "taxonomy": taxonomy, "review": review, "labeling": labeling,
    "analytics": analytics, "schema": schema, "eval": evaluate, "bench": bench,
    "laws": laws, "entities": entities, "editor": editor, "webhooks": webhooks,
}


def main() -> None:
    # Persian / RTL / palette must be injected before anything renders.
    theme.apply()

    # Build the database engine and session factory on *this* thread. Doing it
    # lazily from inside a coroutine would deadlock the background loop — see
    # the module docstring in app/ui/resources.py.
    resources.init()

    try:
        state = data.load()
    except Exception as error:  # noqa: BLE001 — the whole UI depends on this
        st.error(f"اتصال به پایگاه‌داده برقرار نشد — {type(error).__name__}: {error}")
        if st.button("تلاش دوباره"):
            data.refresh()
            st.rerun()
        return

    # Three columns; under RTL the first is the rightmost.
    #   rail (right) · content · panel (left)
    # Both side panels use the same home-made chevron rather than Streamlit's
    # sidebar: its control disappears from the DOM once collapsed, which left
    # the panel unreachable, and Python cannot reopen it.
    rail, content, panel = st.columns([1, 6, 1], gap="medium")

    with rail:
        active = nav.render(state)

    with panel:
        st.markdown(
            f"<div class='model-panel{'' if sidebar.expanded() else ' shut'}'></div>",
            unsafe_allow_html=True,
        )
        if st.button("»" if sidebar.expanded() else "«",
                     key="panel_toggle_open" if sidebar.expanded() else "panel_toggle_shut",
                     help="باز و بسته کردن تنظیمات"):
            st.session_state["show_panel"] = not sidebar.expanded()
            st.rerun()
        if sidebar.expanded():
            config = sidebar.render()
            if st.button("بازخوانی آرشیو", use_container_width=True):
                data.refresh()
                st.rerun()

    if not sidebar.expanded():
        # Collapsed, the panel still has to *run* — every view needs the model
        # and retrieval settings it returns, and its widgets must keep their
        # state. A keyed container that CSS hides does that.
        with st.container(key="hidden_panel"):
            config = sidebar.render()

    with content:
        # Marks the column that absorbs the leftover width beside the two
        # pinned rails; see the note in theme.py.
        st.markdown("<div class='content-col'></div>", unsafe_allow_html=True)
        VIEWS[active].render(config, state)


main()

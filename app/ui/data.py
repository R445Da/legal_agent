"""
The application state every view reads — the equivalent of `loadAll()` in the
old app.html.

Loaded once per re-run and cached, so switching sections does not re-query the
database. `refresh()` clears it after anything writes (an ingest, a commit, a
label, a delete).
"""

import streamlit as st

from app.rag import catalog
from app.rag.cases import all_events, derive_cases, tag_counts
from app.ui import aio
from app.ui.resources import session


@st.cache_data(ttl=120, show_spinner="در حال بارگذاری آرشیو…")
def _load() -> dict:
    async def _go():
        async with session() as s:
            entries = await catalog.list_entries(s)
            return {
                "entries": entries,
                "counts": await catalog.counts(s),
                "collections": (await catalog.collections(s))["collections"],
                "facets": await catalog.facets(s),
                "schema": await catalog.schema_overview(s),
            }

    state = aio.run(_go())
    state["cases"] = derive_cases(state["entries"])
    state["events"] = all_events(state["cases"])
    state["tags"] = tag_counts(state["cases"])
    state["review_queue"] = [c for c in state["cases"] if c["incomplete"]]
    return state


def load() -> dict:
    return _load()


def refresh() -> None:
    """Call after any write so the next render sees it."""
    _load.clear()


def find_case(state: dict, case_id: str) -> dict | None:
    return next((c for c in state["cases"] if str(c["id"]) == str(case_id)), None)

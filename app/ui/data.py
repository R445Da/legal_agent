"""
The application state every view reads — the equivalent of `loadAll()` in the
old app.html.

Loaded once per re-run and cached, so switching sections does not re-query the
database. `refresh()` clears it after anything writes (an ingest, a commit, a
label, a delete).
"""

import streamlit as st

from app.rag import casebase, catalog, lawbase
from app.rag.cases import all_events, derive_cases, tag_counts
from app.rag.textnorm import normalize_fa
from app.ui import aio
from app.ui.resources import session


def _number_key(value) -> str:
    """Entries carry the case number as extracted; `legal_cases` stores it
    folded through `normalize_fa`. Compare both on the folded form."""
    return normalize_fa(str(value or "")).strip()


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
                "legal_cases": await casebase.list_cases(s),
                "law_titles": await lawbase.law_titles(s),
                "archive": await casebase.archive_stats(s),
            }

    state = aio.run(_go())
    state["cases"] = derive_cases(state["entries"])

    # Attach the relational case record (`legal_cases`) to each derived case,
    # matched on the case number. A case with no number has no record.
    by_number = {_number_key(r["case_number"]): r for r in state["legal_cases"]}
    for case in state["cases"]:
        case["record"] = by_number.get(_number_key(case["number"])) if case["number"] else None

    state["events"] = all_events(state["cases"])
    state["tags"] = tag_counts(state["cases"])
    state["review_queue"] = [c for c in state["cases"] if c["incomplete"]]
    return state


def load() -> dict:
    return _load()


# Views may keep their own `st.cache_data` lookups (a law's citing cases, an
# entity profile). They register their clear functions here so one `refresh()`
# after a write empties every cache, not just the main state.
_CLEARERS: list = []


def register_clearer(fn) -> None:
    if fn not in _CLEARERS:
        _CLEARERS.append(fn)


def refresh() -> None:
    """Call after any write so the next render sees it."""
    _load.clear()
    for fn in _CLEARERS:
        try:
            fn()
        except Exception:  # noqa: BLE001 — a stale side cache must not block a write
            pass


def split_list(text: str) -> list[str]:
    """«الف، ب, ج» -> ["الف", "ب", "ج"] — comma-separated input, either comma."""
    out = []
    for piece in str(text or "").replace("،", ",").split(","):
        if piece.strip():
            out.append(piece.strip())
    return out


def find_case(state: dict, case_id: str) -> dict | None:
    """A derived case by its id, its case number, or its record's id."""
    key = str(case_id)
    folded = _number_key(key)
    for c in state["cases"]:
        if str(c["id"]) == key or (c["number"] and _number_key(c["number"]) == folded):
            return c
        record = c.get("record")
        if record and str(record.get("id")) == key:
            return c
    return None

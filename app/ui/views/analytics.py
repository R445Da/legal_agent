"""
۱۱ آمار آرشیو — corpus aggregates, plus a natural-language question over them.

This is the half of the system pure vector search cannot do. "Which cases involve
lawyer X" scores badly on cosine similarity but is a trivial SQL count once the
orchestrator has extracted structured records — which is exactly why the Entry
table exists alongside the chunk index.
"""

import streamlit as st

from app.rag.orchestrator import corpus_stats, run_assistant
from app.ui import aio, components
from app.ui.resources import session
from app.ui.theme import card, esc, fa_num


async def _stats() -> dict:
    async with session() as s:
        return await corpus_stats(s)


async def _ask(llm, text: str) -> dict:
    async with session() as s:
        return await run_assistant(s, llm, text, force_intent="analytics")


def _table(title: str, rows, key_name: str, *, prefix: str) -> None:
    """Each name is a row you can click: it runs the archive query for that
    person or topic rather than making you retype it into search."""
    st.subheader(title)
    if not rows:
        components.empty("موردی استخراج نشده است.")
        return
    components.rowlist_start()
    for index, row in enumerate(rows[:12]):
        if isinstance(row, dict):
            name = row.get(key_name) or row.get("name") or "—"
            count = row.get("count") or row.get("n") or row.get("cases") or ""
        else:
            name, count = row, ""
        if components.row(
            str(name),
            f"{fa_num(count)} مورد" if count != "" else None,
            key=f"{prefix}_{index}",
        ):
            # Open what was clicked, here. These names were extracted from the
            # entries, so the matching cases are already in hand — bouncing to a
            # search box would make the user ask for what we already know.
            st.session_state["open_name"] = str(name)
            st.rerun()


def _matching(state: dict, name: str) -> list[dict]:
    """Cases mentioning this name — as a party, a lawyer, a topic or a tag."""
    needle = name.strip()
    hits = []
    for case in state["cases"]:
        if (
            any(needle == p["name"] for p in case["parties"])
            or any(needle == (r.get("lawyer") or "") for r in case["representation"])
            or needle in case["topics"] or needle in case["tags"]
            or needle == case["court"]
        ):
            hits.append(case)
    return hits


def _open_name(state: dict, name: str) -> None:
    if st.button("→ بازگشت به آمار", key="name_back"):
        st.session_state["open_name"] = None
        st.rerun()

    hits = _matching(state, name)
    st.title(name)
    st.caption(f"{fa_num(len(hits))} پرونده مرتبط")
    if not hits:
        components.empty("پرونده‌ای با این نام یافت نشد.")
        return

    components.rowlist_start()
    for case in hits:
        parties = "، ".join(p["name"] for p in case["parties"][:3])
        if components.row(
            case["title"],
            f"شماره {fa_num(case['number'] or 'ندارد')} · {case['subject']}",
            parties or None,
            key=f"nm_{case['id']}",
        ):
            st.session_state["open_case"] = case["id"]
            st.session_state["view"] = "cases"
            st.rerun()


def render(cfg: dict, state: dict) -> None:
    if st.session_state.get("open_name"):
        _open_name(state, st.session_state["open_name"])
        return

    st.title("آمار آرشیو")
    st.caption("روی هر نام یا موضوع بزنید تا پرونده‌های مرتبطش همین‌جا باز شود.")

    try:
        with st.spinner("در حال تجمیع…"):
            stats = aio.run(_stats())
    except Exception as error:  # noqa: BLE001
        components.error_box(error)
        return

    cols = st.columns(4)
    cols[0].metric("مدخل‌ها", fa_num(stats.get("entries", 0)))
    cols[1].metric("اسناد", fa_num(stats.get("documents", 0)))
    cols[2].metric("قطعات", fa_num(stats.get("chunks", 0)))
    cols[3].metric("پرونده‌ها", fa_num(len(state["cases"])))

    st.divider()
    left, right = st.columns(2)
    with left:
        _table("وکلا", stats.get("lawyers"), "lawyer", prefix="law")
        _table("اشخاص", stats.get("people"), "name", prefix="per")
    with right:
        _table("موضوعات", stats.get("topics"), "topic", prefix="top")
        _table("سازمان‌ها", stats.get("orgs"), "org", prefix="org")

    st.caption(
        "نام‌ها یکسان‌سازی نشده‌اند — «رضا کریمی» و «آقای رضا کریمی» جدا شمرده "
        "می‌شوند. یکسان‌سازی موجودیت‌ها هنوز پیاده نشده است."
    )

    st.divider()
    st.subheader("پرسش دربارهٔ آرشیو")
    question = st.text_input("پرسش", key="an_q", placeholder="چند پرونده کارگری داریم؟")
    if st.button("پرسش", type="primary", disabled=not question.strip()):
        try:
            with st.spinner("در حال پاسخ…"):
                result = aio.run(_ask(cfg["llm"], question))
        except Exception as error:  # noqa: BLE001
            components.error_box(error)
            return
        if result.get("summary"):
            card(f"<div style='line-height:2'>{esc(result['summary'])}</div>")
        components.steps_panel(result.get("steps", []), title="مراحل پردازش")

    with st.expander("دادهٔ خام"):
        st.json(stats)

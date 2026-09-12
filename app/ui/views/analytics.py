"""
۱۱ آمار آرشیو — corpus aggregates, the case-archive aggregates, plus a
natural-language question over them.

This is the half of the system pure vector search cannot do. "Which cases involve
lawyer X" scores badly on cosine similarity but is a trivial SQL count once the
orchestrator has extracted structured records — which is exactly why the Entry
table exists alongside the chunk index.

A name clicked in the lawyers / people / organizations tables opens that
record's profile in «اشخاص و سازمان‌ها». The old behaviour — an exact-match
filter over the derived cases — came back empty for nearly every name, because
the extracted spelling («آقای رضا کریمی») rarely equals the aggregated one;
`casebase.entity_profile` resolves through the normalised name instead.
"""

import pandas as pd
import streamlit as st

from app.rag.orchestrator import corpus_stats, run_assistant
from app.ui import aio, components
from app.ui.resources import session
from app.ui.theme import card, esc, fa_num, ledger

_ENTITY_KIND = {"law": "person", "per": "person", "org": "org"}


async def _stats() -> dict:
    async with session() as s:
        return await corpus_stats(s)


async def _ask(llm, text: str) -> dict:
    async with session() as s:
        return await run_assistant(s, llm, text, force_intent="analytics")


def _table(title: str, rows, key_name: str, *, prefix: str) -> None:
    """Each name is a row you can click: a person or organization opens its
    profile; a topic opens the cases carrying it."""
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
            kind = _ENTITY_KIND.get(prefix)
            if kind:
                st.session_state["open_entity"] = {"kind": kind, "key": str(name)}
                st.session_state["view"] = "entities"
            else:
                st.session_state["open_name"] = str(name)
            st.rerun()


def _matching(state: dict, name: str) -> list[dict]:
    """Cases carrying this topic, tag or court — the non-entity names."""
    needle = name.strip()
    hits = []
    for case in state["cases"]:
        if needle in case["topics"] or needle in case["tags"] or needle == case["court"]:
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
        if st.button("جستجو در اشخاص و سازمان‌ها", key="name_to_entities"):
            st.session_state["open_entity"] = {"kind": "person", "key": name}
            st.session_state["view"] = "entities"
            st.rerun()
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


def _bar(title: str, rows: list[dict], *, label_key: str = "name", top: int | None = None) -> None:
    st.caption(title)
    rows = [r for r in rows if r.get(label_key)]
    if top:
        rows = rows[:top]
    if not rows:
        card("<div class='meta'>—</div>")
        return
    frame = pd.DataFrame(
        {"تعداد": [r["count"] for r in rows]},
        index=[str(r.get(label_key) or r.get("name")) for r in rows],
    )
    st.bar_chart(frame, use_container_width=True, height=260)


def _rial(amount) -> str:
    try:
        return fa_num(f"{int(amount):,}").replace(",", "٬")
    except (TypeError, ValueError):
        return "—"


def _archive_section(archive: dict) -> None:
    st.subheader("آمار بایگانی پرونده‌ها")
    cards = [
        ledger(archive.get("cases", 0), "پرونده‌ها", accent="teal"),
        ledger(archive.get("persons", 0), "اشخاص"),
        ledger(archive.get("orgs", 0), "سازمان‌ها"),
        ledger(archive.get("laws", 0), "مواد قانونی", accent="gold"),
        ledger(archive.get("citations", 0), "استنادها"),
    ]
    st.markdown(
        "<div style='display:grid;grid-template-columns:repeat(5,1fr);gap:14px;margin-bottom:14px'>"
        + "".join(cards) + "</div>",
        unsafe_allow_html=True,
    )
    money = st.columns(2)
    money[0].metric("مجموع خواسته (ریال)", _rial(archive.get("claim_total")))
    money[1].metric("میانگین خواسته (ریال)", _rial(archive.get("claim_avg")))

    left, right = st.columns(2)
    with left:
        _bar("بر اساس نوع دعوا", archive.get("by_type") or [])
        _bar("بر اساس وضعیت", archive.get("by_status") or [], label_key="name_fa")
        _bar("بر اساس مرجع رسیدگی (۱۰ مرجع اول)", archive.get("by_court") or [], top=10)
    with right:
        _bar("بر اساس رشتهٔ بیمه", archive.get("by_line") or [])
        months = [{"name": m, "count": n} for m, n in archive.get("by_month") or []]
        _bar("پرونده‌های طرح‌شده در هر ماه", months)

    st.subheader("پراستنادترین مواد")
    laws = archive.get("top_laws") or []
    if not laws:
        components.empty("استنادی ثبت نشده است.")
        return
    components.rowlist_start()
    for index, row in enumerate(laws):
        cite = (f"مادهٔ {fa_num(row['article'])} " if row.get("article") else "") + str(row.get("law") or "—")
        if components.row(cite, f"{fa_num(row['count'])} استناد", key=f"toplaw_{index}"):
            article = f"ماده {row['article']} " if row.get("article") else ""
            st.session_state["laws_q"] = f"{article}{row.get('law') or ''}".strip()
            st.session_state["law_focus"] = None
            st.session_state["view"] = "laws"
            st.rerun()


def render(cfg: dict, state: dict) -> None:
    if st.session_state.get("open_name"):
        _open_name(state, st.session_state["open_name"])
        return

    st.title("آمار آرشیو")
    st.caption("روی هر نام بزنید تا پروفایلش باز شود؛ روی هر موضوع تا پرونده‌های مرتبطش همین‌جا باز شود.")

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
    _archive_section(state.get("archive") or {})

    st.divider()
    left, right = st.columns(2)
    with left:
        _table("وکلا", stats.get("lawyers"), "lawyer", prefix="law")
        _table("اشخاص", stats.get("people"), "name", prefix="per")
    with right:
        _table("موضوعات", stats.get("topics"), "topic", prefix="top")
        _table("سازمان‌ها", stats.get("orgs"), "org", prefix="org")

    st.caption(
        "شمارش این جدول‌ها روی املای استخراج‌شده است؛ پروفایل هر نام از روی نام "
        "یکسان‌سازی‌شده باز می‌شود، پس «رضا کریمی» و «آقای رضا کریمی» به یک رکورد می‌رسند."
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
        st.json({"corpus": stats, "archive": state.get("archive")})

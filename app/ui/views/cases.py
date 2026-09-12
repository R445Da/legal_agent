"""
۰۳ پرونده‌ها — entries folded into cases, and the case-detail view.

A case is every entry sharing a case number (see `app/rag/cases.py`). The detail
view keeps the five folder tabs of the original UI: خلاصه، تایم‌لاین،
اسناد و مدخل‌ها، پرونده‌های مشابه، وضعیت و مالی.
"""

import streamlit as st

from app.ui import components
from app.ui.theme import card, case_id, chips, esc, fa_num, kv, panel, stamp, timeline

_ROLE_FA = {
    "plaintiff": "خواهان", "defendant": "خوانده", "lawyer": "وکیل",
    "judge": "قاضی", "witness": "شاهد", "expert": "کارشناس", "other": "سایر",
}

CASE_TABS = ["خلاصه", "تایم‌لاین", "اسناد و مدخل‌ها", "پرونده‌های مشابه", "وضعیت و مالی"]


def _case_card(case: dict, *, on_open) -> None:
    """The row is the control — clicking the case opens it."""
    parties = "، ".join(p["name"] for p in case["parties"][:3])
    status = "ناقص: " + "، ".join(case["incomplete_reasons"]) if case["incomplete"] else "کامل"
    if components.row(
        case["title"],
        f"شماره {fa_num(case['number'] or 'ندارد')} · {case['subject']} · {case['court']}",
        parties or None,
        "، ".join(case["tags"][:4]) or None,
        status,
        key=f"case_{case['id']}",
    ):
        on_open(case["id"])


def _tab_summary(case: dict) -> None:
    card(
        kv([
            ("شمارهٔ پرونده", fa_num(case["number"] or "استخراج نشده")),
            ("موضوع", case["subject"]),
            ("مرجع رسیدگی", case["court"]),
            ("تعداد مدخل‌ها", fa_num(len(case["entries"]))),
            ("آخرین رویداد", fa_num(case["last_event_date"] or "—")),
        ])
    )
    st.subheader("طرفین")
    if case["parties"]:
        card("".join(
            f"<div class='kv'><span class='k'>{esc(_ROLE_FA.get(p['role'], p['role']))}</span>"
            f"<span>{esc(p['name'])}</span></div>"
            for p in case["parties"]
        ))
    else:
        components.empty("طرفینی استخراج نشده است.")

    if case["representation"]:
        st.subheader("وکالت")
        card("".join(
            f"<div class='kv'><span class='k'>{esc(r.get('lawyer'))}</span>"
            f"<span>{esc(r.get('for') or r.get('party') or '—')}</span></div>"
            for r in case["representation"]
        ))

    st.subheader("برچسب‌ها")
    card(chips(case["tags"], teal=True))


def _tab_timeline(case: dict) -> None:
    if not case["events"]:
        components.empty("رویدادی ثبت نشده است.")
        return
    card(timeline([
        {
            "date": e.get("date"),
            "title": e.get("what") or e.get("type") or "—",
            "detail": e.get("detail"),
        }
        for e in case["events"]
    ]))


def _tab_documents(case: dict, *, on_open_doc) -> None:
    components.rowlist_start()
    for entry in case["entries"]:
        if components.row(
            entry.get("title") or "بدون عنوان",
            entry.get("summary"),
            f"نوع: {entry.get('kind') or '—'} · ثبت: {fa_num((entry.get('created_at') or '—')[:10])}",
            key=f"cd_{entry['id']}",
        ) and entry.get("document_id"):
            on_open_doc(entry["document_id"])


def _tab_similar(case: dict, state: dict, *, on_open) -> None:
    # First: the links the build pipeline recorded on this case's entries, with
    # a match score and the past outcome (the «پرونده‌های مشابه» of the mock-up).
    links = case.get("related_links") or []
    if links:
        st.caption("این فهرست تاریخی است، نه پیش‌بینی نتیجهٔ پروندهٔ جاری.")
        rows = ""
        for link in links[:10]:
            score = link.get("score")
            pct = int(round(score * 100)) if isinstance(score, (int, float)) else None
            bar = (
                f"<div class='bar-track'><div class='bar-fill' style='width:{pct}%'></div></div>"
                if pct is not None else ""
            )
            rows += (
                "<div style='padding:10px 0;border-bottom:1px solid var(--line)'>"
                f"<div style='display:flex;justify-content:space-between;gap:10px'>"
                f"<b style='font-size:12.8px'>{esc(link.get('title') or 'بدون عنوان')}</b>"
                + (f"<span class='sim-pct'>{fa_num(pct)}٪</span>" if pct is not None else "")
                + "</div>"
                + (f"<div class='meta'>نتیجه: {esc(link['outcome'])}</div>" if link.get("outcome") else "")
                + bar + "</div>"
            )
        card(rows)

    # Then: other cases in the archive that share a tag or a linked record.
    related_ids = set(case["related_ids"])
    shared_tags = set(case["tags"])
    similar = [
        c for c in state["cases"]
        if c["id"] != case["id"] and (
            related_ids & {e["id"] for e in c["entries"]} or shared_tags & set(c["tags"])
        )
    ]
    if not similar:
        if not links:
            components.empty("پروندهٔ مشابهی یافت نشد.")
        return
    st.subheader("پرونده‌های هم‌موضوع در آرشیو")
    components.rowlist_start()
    for other in similar[:10]:
        _case_card(other, on_open=on_open)


def _tab_status(case: dict) -> None:
    entities = {}
    for entry in case["entries"]:
        entities.update(entry.get("entities") or {})
    money = [(k, v) for k, v in entities.items() if any(
        token in k for token in ("amount", "مبلغ", "value", "claim")
    )]
    card(kv([
        ("وضعیت", entities.get("status") or "—"),
        ("شعبه", entities.get("branch") or "—"),
        ("سال", fa_num(entities.get("year") or "—")),
        ("نوع سند", entities.get("doc_kind") or "—"),
    ]))
    st.subheader("مالی")
    card(kv([(k, fa_num(v)) for k, v in money]) if money else "<div class='meta'>موردی ثبت نشده.</div>")

    st.subheader("همهٔ فیلدهای استخراج‌شده")
    st.json(entities, expanded=False)


def _detail(case: dict, state: dict, *, on_open, on_open_doc) -> None:
    if st.button("→ بازگشت به فهرست", key="case_back"):
        st.session_state["open_case"] = None
        st.rerun()

    st.title(case["title"])
    st.markdown(
        f"<div style='direction:rtl;text-align:right;margin-bottom:6px'>{case_id(case['number'])}"
        f"<span class='meta' style='margin-inline-start:10px'>"
        f"{fa_num(len(case['entries']))} مدخل · {fa_num(len(case['events']))} رویداد</span></div>",
        unsafe_allow_html=True,
    )
    if case["incomplete"]:
        st.warning("این پرونده ناقص است: " + "، ".join(case["incomplete_reasons"]))

    tabs = st.tabs(CASE_TABS)
    with tabs[0]:
        _tab_summary(case)
    with tabs[1]:
        _tab_timeline(case)
    with tabs[2]:
        _tab_documents(case, on_open_doc=on_open_doc)
    with tabs[3]:
        _tab_similar(case, state, on_open=on_open)
    with tabs[4]:
        _tab_status(case)


def render(cfg: dict, state: dict) -> None:
    def on_open(case_id):
        st.session_state["open_case"] = case_id
        st.rerun()

    def on_open_doc(document_id):
        st.session_state["open_doc"] = document_id
        st.session_state["view"] = "documents"
        st.rerun()

    open_case = st.session_state.get("open_case")
    if open_case:
        from app.ui.data import find_case
        case = find_case(state, open_case)
        if case:
            _detail(case, state, on_open=on_open, on_open_doc=on_open_doc)
            return
        st.session_state["open_case"] = None

    st.title("پرونده‌ها")

    tag_filter = st.session_state.get("tag_filter")
    cases = state["cases"]
    if tag_filter:
        cases = [c for c in cases if tag_filter in c["tags"]]
        bar = st.columns([4, 1])
        bar[0].caption(f"فیلتر برچسب: **{tag_filter}**")
        if bar[1].button("حذف فیلتر", use_container_width=True):
            st.session_state["tag_filter"] = None
            st.rerun()

    query = st.text_input(
        "جستجو", key="cases_q", label_visibility="collapsed",
        placeholder="جستجو در عنوان، شمارهٔ پرونده یا نام طرفین…",
    )
    if query:
        needle = query.strip()
        cases = [
            c for c in cases
            if needle in str(c["title"]) or needle in str(c["number"] or "")
            or any(needle in p["name"] for p in c["parties"])
        ]

    # Ordering was "most entries, then latest event", which reads as random.
    # Newest first by default, and the choice is the user's.
    order = st.radio(
        "ترتیب", ["تازه‌ترین رویداد", "شمارهٔ پرونده", "بیشترین مدخل"],
        horizontal=True, key="cases_order", label_visibility="collapsed",
    )
    if order == "تازه‌ترین رویداد":
        cases = sorted(cases, key=lambda c: str(c["last_event_date"] or ""), reverse=True)
    elif order == "شمارهٔ پرونده":
        cases = sorted(cases, key=lambda c: str(c["number"] or "\uffff"))
    else:
        cases = sorted(cases, key=lambda c: len(c["entries"]), reverse=True)

    st.caption(f"{fa_num(len(cases))} پرونده — روی هر پرونده بزنید تا باز شود")
    if not cases:
        components.empty("پرونده‌ای یافت نشد.")
        return
    components.rowlist_start()
    for case in cases:
        _case_card(case, on_open=on_open)

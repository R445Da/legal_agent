"""
۱۷ ویرایش مدخل‌ها — full editing of a structured entry: its text fields, the
case fields the record is built from, and the four tables (parties,
representation, events, legal references). Saving goes through
`catalog.update_entry`, which re-syncs the case, the persons and organizations,
the citations and the graph — so an edit here is visible everywhere.

Other views hand this one an entry: `st.session_state["edit_entry"] = id`.
New entries are not typed here; they come through the assistant's
human-in-the-loop pipeline (the «ثبت مدخل جدید» button jumps there).
"""

import pandas as pd
import streamlit as st

from app.rag import casebase, catalog, graph
from app.rag.casebase import ROLE_FA, STATUS_FA
from app.rag.orchestrator import CASE_TYPES, INSURANCE_LINES
from app.ui import aio, components, data
from app.ui.data import split_list
from app.ui.resources import session
from app.ui.theme import card, esc, fa_num, kv

_OTHER = "سایر"
_NONE = "—"
_ROLE_BY_FA = {v: k for k, v in ROLE_FA.items()}
_KIND_FA = {"session": "صورت‌جلسه", "note": "یادداشت"}


async def _entry(entry_id: str) -> dict | None:
    async with session() as s:
        return await catalog.get_entry(s, entry_id)


async def _save(entry_id: str, patch: dict) -> dict | None:
    async with session() as s:
        return await catalog.update_entry(s, entry_id, patch)


async def _delete(entry_id: str) -> bool:
    async with session() as s:
        return await catalog.delete_entry(s, entry_id, with_document=True)


async def _case(case_id: str) -> dict | None:
    async with session() as s:
        return await casebase.get_case(s, case_id)


async def _dot(case_id: str) -> str:
    async with session() as s:
        return graph.to_dot(await graph.neighborhood(s, "case", case_id, depth=1))


# --------------------------------------------------------------------------- #
# table helpers
# --------------------------------------------------------------------------- #
def _clean(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value).strip()


def _records(df: pd.DataFrame, required: tuple[str, ...]) -> list[dict]:
    """The editor's rows back as dicts, blank rows dropped."""
    out = []
    for raw in df.to_dict("records"):
        row = {k: _clean(v) if not isinstance(v, bool) else v for k, v in raw.items()}
        if all(row.get(k) for k in required):
            out.append(row)
    return out


def _parties_editor(parties: list, key: str) -> list[dict]:
    rows = [
        {"name": _clean(p.get("name")), "role": ROLE_FA.get(p.get("role"), _clean(p.get("role")) or ROLE_FA["other"])}
        for p in parties if isinstance(p, dict)
    ]
    options = list(ROLE_FA.values())
    for r in rows:
        if r["role"] not in options:
            options.append(r["role"])
    df = st.data_editor(
        pd.DataFrame(rows, columns=["name", "role"]),
        num_rows="dynamic", use_container_width=True, key=key, hide_index=True,
        column_config={
            "name": st.column_config.TextColumn("نام", required=True),
            "role": st.column_config.SelectboxColumn("نقش", options=options, required=True),
        },
    )
    return [
        {"name": r["name"], "role": _ROLE_BY_FA.get(r["role"], r["role"])}
        for r in _records(df, ("name",))
    ]


def _pairs_editor(rows: list, key: str, a: tuple[str, str], b: tuple[str, str], *, required=None) -> list[dict]:
    """A two-column table: (key, label) for each column."""
    (ka, la), (kb, lb) = a, b
    data_rows = [{ka: _clean(r.get(ka)), kb: _clean(r.get(kb))} for r in rows if isinstance(r, dict)]
    df = st.data_editor(
        pd.DataFrame(data_rows, columns=[ka, kb]),
        num_rows="dynamic", use_container_width=True, key=key, hide_index=True,
        column_config={
            ka: st.column_config.TextColumn(la),
            kb: st.column_config.TextColumn(lb, width="large"),
        },
    )
    return _records(df, required or (ka, kb))


def _refs_editor(refs: list, key: str) -> list[dict]:
    rows = [
        {
            "law": _clean(r.get("law")), "article": _clean(r.get("article")),
            "context": _clean(r.get("context")), "used_by": _clean(r.get("used_by")),
            "resolved": bool(r.get("resolved")),
        }
        for r in refs if isinstance(r, dict)
    ]
    df = st.data_editor(
        pd.DataFrame(rows, columns=["law", "article", "context", "used_by", "resolved"]),
        num_rows="dynamic", use_container_width=True, key=key, hide_index=True,
        column_config={
            "law": st.column_config.TextColumn("قانون", required=True, width="medium"),
            "article": st.column_config.TextColumn("ماده", width="small"),
            "context": st.column_config.TextColumn("نحوهٔ استناد", width="large"),
            "used_by": st.column_config.TextColumn("استنادکننده", width="small"),
            "resolved": st.column_config.CheckboxColumn("حل‌شده", disabled=True, default=False),
        },
        disabled=["resolved"],
    )
    return [
        {k: v for k, v in r.items() if k != "resolved"}
        for r in _records(df, ("law",))
    ]


def _choice(label: str, options: list[str], current: str, key: str) -> str:
    """A selectbox over a fixed vocabulary, with «سایر» opening a free field —
    so a value the vocabulary does not know is kept, not silently dropped."""
    current = _clean(current)
    menu = [_NONE] + options + [_OTHER]
    if current in options:
        index = menu.index(current)
    elif current:
        index = menu.index(_OTHER)
    else:
        index = 0
    picked = st.selectbox(label, menu, index=index, key=f"{key}_sel")
    if picked == _OTHER:
        return st.text_input(f"{label} (دلخواه)", value=current if current not in options else "", key=f"{key}_free")
    return "" if picked == _NONE else picked


# --------------------------------------------------------------------------- #
# the form
# --------------------------------------------------------------------------- #
def _form(entry: dict, rev: int) -> None:
    eid = entry["id"]
    k = f"ed_{eid}_{rev}"
    ent = entry.get("entities") or {}

    st.subheader(entry.get("title") or "بدون عنوان")
    st.caption(
        f"ثبت: {fa_num((entry.get('created_at') or '—')[:10])}"
        + (f" · پروندهٔ متصل: {fa_num(ent.get('case_number'))}" if ent.get("case_number") else " · بدون پرونده")
    )

    head = st.columns([4, 1])
    title = head[0].text_input("عنوان", value=entry.get("title") or "", key=f"{k}_title")
    kinds = list(_KIND_FA)
    kind_now = entry.get("kind") if entry.get("kind") in kinds else kinds[0]
    kind = head[1].selectbox("نوع", kinds, index=kinds.index(kind_now), format_func=lambda x: _KIND_FA[x], key=f"{k}_kind")
    summary = st.text_area("چکیده", value=entry.get("summary") or "", height=110, key=f"{k}_summary")

    st.markdown("**مشخصات پرونده**")
    r1 = st.columns(3)
    case_number = r1[0].text_input("شمارهٔ پرونده", value=_clean(ent.get("case_number")), key=f"{k}_num")
    court = r1[1].text_input("مرجع رسیدگی", value=_clean(ent.get("court")), key=f"{k}_court")
    topic = r1[2].text_input("موضوع", value=_clean(ent.get("topic")), key=f"{k}_topic")

    r2 = st.columns(2)
    with r2[0]:
        case_type = _choice("نوع دعوا", CASE_TYPES, ent.get("case_type"), f"{k}_ctype")
    with r2[1]:
        insurance_line = _choice("رشتهٔ بیمه", INSURANCE_LINES, ent.get("insurance_line"), f"{k}_line")

    r3 = st.columns(4)
    statuses = list(STATUS_FA)
    status_now = ent.get("status") if ent.get("status") in statuses else statuses[0]
    status = r3[0].selectbox("وضعیت", statuses, index=statuses.index(status_now),
                             format_func=lambda x: STATUS_FA[x], key=f"{k}_status")
    stage = r3[1].text_input("مرحله", value=_clean(ent.get("stage")), key=f"{k}_stage")
    filed_date = r3[2].text_input("تاریخ طرح", value=_clean(ent.get("filed_date")), key=f"{k}_filed", placeholder="۱۴۰۳/۰۱/۰۷")
    claim_amount = r3[3].text_input("مبلغ خواسته (ریال)", value=_clean(ent.get("claim_amount")), key=f"{k}_amount")
    outcome = st.text_input("نتیجه", value=_clean(ent.get("outcome")), key=f"{k}_outcome")
    tags = st.text_input("برچسب‌ها (با ویرگول جدا کنید)", value="، ".join(str(t) for t in entry.get("tags") or []), key=f"{k}_tags")

    st.markdown("**طرفین**")
    parties = _parties_editor(entry.get("parties") or [], f"{k}_parties")
    st.markdown("**وکالت**")
    representation = _pairs_editor(entry.get("representation") or [], f"{k}_rep", ("lawyer", "وکیل"), ("client", "موکل"))
    st.markdown("**رویدادها**")
    events_in = [
        {"date": e.get("date"), "description": e.get("description") or e.get("what") or e.get("detail")}
        for e in (entry.get("events") or []) if isinstance(e, dict)
    ]
    events = _pairs_editor(events_in, f"{k}_events", ("date", "تاریخ"), ("description", "شرح"), required=("description",))
    st.markdown("**مستندات قانونی**")
    st.caption("پس از ذخیره، هر ارجاع به پایگاه قوانین متصل می‌شود؛ ماده‌ای که در پایگاه نباشد «حل‌نشده» می‌ماند.")
    legal_refs = _refs_editor(entry.get("legal_refs") or [], f"{k}_refs")

    with st.expander("متن خام"):
        st.markdown(
            f"<div style='white-space:pre-wrap;line-height:2'>{esc(entry.get('raw_text') or '—')}</div>",
            unsafe_allow_html=True,
        )

    st.divider()
    actions = st.columns([1, 1, 2])
    if actions[0].button("ذخیره", key=f"{k}_save", type="primary", use_container_width=True):
        patch = {
            "title": title.strip(), "kind": kind, "summary": summary.strip(),
            "entities": {
                "case_number": case_number.strip(), "court": court.strip(), "topic": topic.strip(),
                "case_type": case_type.strip(), "insurance_line": insurance_line.strip(),
                "claim_amount": claim_amount.strip(), "outcome": outcome.strip(), "status": status,
                "filed_date": filed_date.strip(), "stage": stage.strip(),
            },
            "tags": split_list(tags), "parties": parties, "representation": representation,
            "events": events, "legal_refs": legal_refs,
        }
        try:
            with st.spinner("در حال ذخیره و همگام‌سازی پرونده…"):
                saved = aio.run(_save(eid, patch))
        except Exception as error:  # noqa: BLE001
            components.error_box(error)
        else:
            if saved is None:
                st.warning("مدخل پیدا نشد.")
            else:
                data.refresh()
                st.session_state["ed_rev"] = rev + 1
                st.session_state["ed_flash"] = "ذخیره شد و پرونده، اشخاص و گراف همگام شدند."
                st.rerun()

    confirm = actions[1].checkbox("تأیید حذف", key=f"{k}_confirm")
    if actions[1].button("حذف مدخل", key=f"{k}_del", disabled=not confirm, use_container_width=True):
        try:
            ok = aio.run(_delete(eid))
        except Exception as error:  # noqa: BLE001
            components.error_box(error)
        else:
            data.refresh()
            st.session_state["edit_entry"] = None
            st.session_state["ed_flash"] = "مدخل حذف شد." if ok else "مدخل پیدا نشد."
            st.rerun()


def _case_panel(case_id: str) -> None:
    """The record this entry feeds, as the archive now holds it."""
    try:
        record = aio.run(_case(case_id))
    except Exception as error:  # noqa: BLE001
        components.error_box(error)
        return
    if not record:
        return
    st.subheader("پروندهٔ حاصل")
    amount = record.get("claim_amount")
    card(
        f"<h4>{esc(record.get('title') or record['case_number'])}</h4>"
        + kv([
            ("شمارهٔ پرونده", fa_num(record["case_number"])),
            ("نوع دعوا", record.get("case_type") or "—"),
            ("رشتهٔ بیمه", record.get("insurance_line") or "—"),
            ("وضعیت", record.get("status_fa") or "—"),
            ("مرحله", record.get("stage") or "—"),
            ("مبلغ خواسته", (fa_num(f"{amount:,}").replace(",", "٬") + " ریال") if amount else "—"),
            ("نتیجه", record.get("outcome") or "—"),
            ("طرفین", "، ".join(f"{p['name']} ({p['role_fa']})" for p in record.get("parties") or []) or "—"),
            ("مستندات", "؛ ".join(r["cite"] for r in record.get("references") or []) or "—"),
            ("مدخل‌ها", fa_num(len(record.get("entries") or []))),
        ])
    )
    cols = st.columns([1, 3])
    if cols[0].button("باز کردن پرونده", key=f"ed_open_case_{case_id}", use_container_width=True):
        st.session_state["open_case"] = record["case_number"]
        st.session_state["view"] = "cases"
        st.rerun()
    with st.expander("گراف"):
        try:
            st.graphviz_chart(aio.run(_dot(case_id)), use_container_width=True)
        except Exception as error:  # noqa: BLE001
            components.error_box(error)


# --------------------------------------------------------------------------- #
def _matches(entry: dict, needle: str) -> bool:
    ent = entry.get("entities") or {}
    if needle in str(entry.get("title") or "") or needle in str(ent.get("case_number") or ""):
        return True
    return any(needle in str(p.get("name") or "") for p in entry.get("parties") or [] if isinstance(p, dict))


def render(cfg: dict, state: dict) -> None:
    st.title("ویرایش مدخل‌ها")
    top = st.columns([3, 1])
    top[0].caption("یک مدخل را از فهرست انتخاب کنید؛ ذخیره، پرونده و اشخاص و گراف را همگام می‌کند.")
    if top[1].button("ثبت مدخل جدید از طریق دستیار", key="ed_new", use_container_width=True):
        st.session_state["view"] = "agent"
        st.session_state["compose_intent"] = "archive"
        st.session_state["agent_intent"] = "archive"
        st.rerun()

    if st.session_state.get("ed_flash"):
        st.success(st.session_state.pop("ed_flash"))

    entries = state["entries"]
    selected_id = st.session_state.get("edit_entry")

    form_col, list_col = st.columns([5, 2], gap="medium")

    with list_col:
        st.markdown("<div class='panel-title'>مدخل‌ها</div>", unsafe_allow_html=True)
        query = st.text_input(
            "جستجو", key="ed_q", label_visibility="collapsed",
            placeholder="عنوان، شمارهٔ پرونده یا نام طرف…",
        )
        rows = entries
        if query and query.strip():
            needle = query.strip()
            rows = [e for e in entries if _matches(e, needle)]
        st.caption(f"{fa_num(len(rows))} مدخل" + (" · ۶۰ مورد اول" if len(rows) > 60 else ""))
        components.rowlist_start()
        for e in rows[:60]:
            ent = e.get("entities") or {}
            if components.row(
                e.get("title") or "بدون عنوان",
                f"شماره {fa_num(ent.get('case_number') or 'ندارد')} · {_KIND_FA.get(e.get('kind'), e.get('kind') or '—')}",
                key=f"edrow_{e['id']}",
                kind="primary" if e["id"] == selected_id else "",
            ):
                st.session_state["edit_entry"] = e["id"]
                st.rerun()

    with form_col:
        if not selected_id:
            components.empty("مدخلی انتخاب نشده است — از فهرست یکی را انتخاب کنید.")
            return
        try:
            entry = aio.run(_entry(selected_id))
        except Exception as error:  # noqa: BLE001
            components.error_box(error)
            return
        if not entry:
            st.warning("مدخل پیدا نشد؛ شاید حذف شده باشد.")
            st.session_state["edit_entry"] = None
            return
        rev = st.session_state.setdefault("ed_rev", 0)
        _form(entry, rev)
        if entry.get("case_id"):
            st.divider()
            _case_panel(entry["case_id"])

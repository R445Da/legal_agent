"""
۱۶ اشخاص و سازمان‌ها — every lawyer, judge, party, insurer and court as a
record of its own (`persons`, `organizations`), with a profile: the roles it
has held, every case it appears in, whom it represented, and its neighbourhood
in the graph.

Other views open a profile by setting
`st.session_state["open_entity"] = {"kind": "person" | "org", "key": id-or-name}`.
The lookup goes through `casebase.entity_profile`, which resolves an id, an
exact normalised name, or a loose name match — so a name clicked in the
statistics tables lands on the right record instead of an empty page.
"""

import streamlit as st

from app.rag import casebase, graph
from app.rag.graph import NODE_FA
from app.ui import aio, components
from app.ui.resources import session
from app.ui.theme import card, chips, fa_num, kv, stamp

_KIND_FA = {"person": "اشخاص", "org": "سازمان‌ها"}
_ORG_KIND_FA = {
    "insurer": "شرکت بیمه", "regulator": "نهاد ناظر", "court": "مرجع قضایی", "fund": "صندوق",
    "bank": "بانک", "agency": "سازمان دولتی", "company": "شرکت",
}


def _norm_kind(kind) -> str:
    return "org" if str(kind or "").startswith("org") else "person"


async def _list(kind: str, q: str | None) -> list[dict]:
    async with session() as s:
        return await casebase.list_entities(s, kind, q=q or None)


async def _profile(kind: str, key: str) -> dict | None:
    async with session() as s:
        return await casebase.entity_profile(s, kind, key)


async def _dot(kind: str, entity_id: str) -> str:
    async with session() as s:
        hood = await graph.neighborhood(
            s, kind, entity_id, depth=1, skip_types=("label", "entry", "document"),
        )
    return graph.to_dot(hood)


def open_entity(kind: str, key: str) -> None:
    """Navigate to a profile from any view."""
    st.session_state["open_entity"] = {"kind": _norm_kind(kind), "key": str(key)}
    st.session_state["view"] = "entities"
    st.rerun()


def _open_case(case_number: str) -> None:
    st.session_state["open_case"] = case_number
    st.session_state["view"] = "cases"
    st.rerun()


def _breakdown(title: str, rows: list) -> None:
    st.caption(title)
    if not rows:
        card("<div class='meta'>—</div>")
        return
    card(kv([(str(name), fa_num(count)) for name, count in rows[:8]]))


def _profile_view(kind: str, key: str) -> None:
    if st.button("→ بازگشت به فهرست", key="ent_back"):
        st.session_state["open_entity"] = None
        st.rerun()

    try:
        profile = aio.run(_profile(kind, key))
    except Exception as error:  # noqa: BLE001
        components.error_box(error)
        return
    if not profile:
        st.warning(f"رکوردی برای «{key}» در {_KIND_FA[kind]} پیدا نشد.")
        return

    st.title(profile["name"])
    org_kind = _ORG_KIND_FA.get(profile.get("kind"), profile.get("kind")) if kind == "org" else None
    st.markdown(
        "<div style='direction:rtl;text-align:right;margin-bottom:8px'>"
        + stamp(NODE_FA.get(kind, kind) + (f" · {org_kind}" if org_kind else ""), "teal")
        + " " + chips(profile["roles_fa"]) + "</div>",
        unsafe_allow_html=True,
    )

    cols = st.columns(3)
    cols[0].metric("تعداد پرونده", fa_num(profile["case_count"]))
    cols[1].metric("موکلان", fa_num(len(profile["represents"])))
    cols[2].metric("وکلا", fa_num(len(profile["represented_by"])))

    st.subheader("پرونده‌ها")
    if not profile["cases"]:
        components.empty("این رکورد در هیچ پرونده‌ای طرف نبوده است.")
    components.rowlist_start()
    for c in profile["cases"]:
        if components.row(
            c.get("title") or c["case_number"],
            f"شماره {fa_num(c['case_number'])} · نقش: {c['role_fa']}",
            " · ".join(x for x in (c.get("case_type"), c.get("insurance_line"), c.get("status_fa")) if x),
            f"نتیجه: {c['outcome']}" if c.get("outcome") else None,
            key=f"entcase_{c['id']}",
        ):
            _open_case(c["case_number"])

    if profile["represents"] or profile["represented_by"]:
        st.subheader("وکالت")
        left, right = st.columns(2)
        with left:
            st.caption("وکیلِ")
            if profile["represents"]:
                components.rowlist_start()
                for index, item in enumerate(profile["represents"]):
                    if components.row(
                        item["name"],
                        f"پروندهٔ {fa_num(item['case'])}" if item.get("case") else None,
                        key=f"rep_{index}_{item['id']}",
                    ):
                        open_entity(item["type"], item["id"])
            else:
                card("<div class='meta'>—</div>")
        with right:
            st.caption("با وکالتِ")
            if profile["represented_by"]:
                components.rowlist_start()
                for index, item in enumerate(profile["represented_by"]):
                    if components.row(
                        item["name"],
                        f"پروندهٔ {fa_num(item['case'])}" if item.get("case") else None,
                        key=f"repby_{index}_{item['id']}",
                    ):
                        open_entity(item["type"], item["id"])
            else:
                card("<div class='meta'>—</div>")

    st.subheader("تفکیک")
    b1, b2, b3 = st.columns(3)
    with b1:
        _breakdown("بر اساس رشتهٔ بیمه", profile["by_line"])
    with b2:
        _breakdown("بر اساس نوع دعوا", profile["by_type"])
    with b3:
        _breakdown("بر اساس نتیجه", profile["by_outcome"])

    with st.expander("گراف ارتباطات"):
        try:
            st.graphviz_chart(aio.run(_dot(kind, profile["id"])), use_container_width=True)
        except Exception as error:  # noqa: BLE001
            components.error_box(error)


def render(cfg: dict, state: dict) -> None:
    opened = st.session_state.get("open_entity")
    if isinstance(opened, dict) and opened.get("key"):
        _profile_view(_norm_kind(opened.get("kind")), str(opened["key"]))
        return

    st.title("اشخاص و سازمان‌ها")
    st.caption("هر نام یک رکورد است. روی هر ردیف بزنید تا پروفایل، پرونده‌ها و گراف ارتباطاتش باز شود.")

    kind = st.radio(
        "نوع", ["person", "org"], format_func=lambda k: _KIND_FA[k],
        horizontal=True, key="ent_kind", label_visibility="collapsed",
    )
    query = st.text_input(
        "جستجو", key="ent_q", label_visibility="collapsed",
        placeholder="جستجوی نام…",
    )

    try:
        rows = aio.run(_list(kind, query.strip() if query else None))
    except Exception as error:  # noqa: BLE001
        components.error_box(error)
        return

    archive = state.get("archive") or {}
    total = archive.get("persons" if kind == "person" else "orgs", len(rows))
    st.caption(f"{fa_num(len(rows))} از {fa_num(total)} {_KIND_FA[kind]}")
    if not rows:
        components.empty("موردی یافت نشد.")
        return

    components.rowlist_start()
    for r in rows:
        detail = "، ".join(r["roles_fa"]) or "بدون نقش"
        if kind == "org" and r.get("kind"):
            detail = f"{_ORG_KIND_FA.get(r['kind'], r['kind'])} · {detail}"
        if components.row(
            r["name"], detail, f"{fa_num(r['cases'])} پرونده", key=f"ent_{r['id']}",
        ):
            st.session_state["open_entity"] = {"kind": kind, "key": r["id"]}
            st.rerun()

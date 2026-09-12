"""
۱۵ قوانین و مستندات — the legal context: every statute article, regulation
and precedent the archive's cases cite (`legal_refs`), browsable by law and
searchable, with the cases that rely on each article one click away.

Other views hand this one a focus: `st.session_state["law_focus"]` (a ref id,
from the case detail) opens that law with the article first; `laws_q` (from the
statistics table) pre-fills the search box.
"""

import streamlit as st

from app.rag import graph, lawbase
from app.rag.lawbase import KIND_FA
from app.ui import aio, components, data
from app.ui.data import split_list
from app.ui.resources import session
from app.ui.theme import card, chips, esc, fa_num

_KIND_CLASS = {"law": "teal", "regulation": "gray", "precedent": "review", "circular": "gray", "stub": "red"}
_PAGE = 40


async def _search(text: str) -> list[dict]:
    async with session() as s:
        return await lawbase.search_laws(s, text, limit=30)


async def _articles(law_title: str | None) -> list[dict]:
    async with session() as s:
        return await lawbase.list_laws(s, law_title=law_title)


async def _ref(ref_id: str) -> dict | None:
    async with session() as s:
        return await lawbase.get_ref(s, ref_id)


async def _citing(ref_id: str) -> list[dict]:
    """The cases citing one article — the law node's neighbourhood."""
    async with session() as s:
        hood = await graph.neighborhood(s, "law", ref_id, depth=1)
    return [n for n in hood["nodes"] if n["type"] == "case"]


@st.cache_data(ttl=120, show_spinner=False)
def _citing_cached(ref_id: str) -> list[dict]:
    return aio.run(_citing(ref_id))


data.register_clearer(_citing_cached.clear)


async def _add(fields: dict) -> dict:
    async with session() as s:
        row = await lawbase.upsert_ref(s, **fields)
        await s.commit()
        return lawbase.as_dict(row)


def _open_case(case_number: str) -> None:
    st.session_state["open_case"] = case_number
    st.session_state["view"] = "cases"
    st.rerun()


def _article_card(ref: dict, *, focused: bool = False) -> None:
    kind = ref.get("kind") or "law"
    head = (
        f"<div style='display:flex;justify-content:space-between;gap:10px;align-items:center'>"
        f"<h4 style='margin:0'>{esc(ref['cite'])}</h4>"
        f"<span class='stamp {_KIND_CLASS.get(kind, 'gray')}' style='flex:none;white-space:nowrap'><span class='dotc'></span>"
        f"{esc(KIND_FA.get(kind, kind))}</span></div>"
    )
    title = f"<div class='meta' style='font-weight:600;margin-top:4px'>{esc(ref['title'])}</div>" if ref.get("title") else ""
    text = (
        f"<div style='white-space:pre-wrap;line-height:2;margin-top:8px'>{esc(ref['text'])}</div>"
        if ref.get("text") else "<div class='meta' style='margin-top:8px'>متن ماده در پایگاه نیست.</div>"
    )
    keywords = (
        f"<div style='margin-top:8px'>{chips(ref['keywords'])}</div>" if ref.get("keywords") else ""
    )
    card(head + title + text + keywords, warn=focused)

    with st.expander("پرونده‌های استنادکننده"):
        try:
            cases = _citing_cached(ref["id"])
        except Exception as error:  # noqa: BLE001
            components.error_box(error)
            return
        if not cases:
            st.caption("هیچ پرونده‌ای به این ماده استناد نکرده است.")
            return
        st.caption(f"{fa_num(len(cases))} پرونده")
        components.rowlist_start()
        for node in cases:
            if components.row(
                node.get("label") or node.get("case_number") or "—",
                f"شماره {fa_num(node.get('case_number') or '—')}"
                + (f" · {node['case_type']}" if node.get("case_type") else "")
                + (f" · {node['insurance_line']}" if node.get("insurance_line") else ""),
                key=f"lawcase_{ref['id']}_{node['id']}",
            ):
                _open_case(node.get("case_number") or node["id"])


def _add_form(default_title: str) -> None:
    with st.expander("افزودن مادهٔ جدید"):
        with st.form("law_add", clear_on_submit=True):
            top = st.columns([3, 1, 1])
            law_title = top[0].text_input("عنوان قانون", value=default_title, placeholder="قانون بیمه")
            law_year = top[1].text_input("سال تصویب", placeholder="۱۳۱۶")
            article_no = top[2].text_input("شمارهٔ ماده", placeholder="۳۰")
            mid = st.columns([1, 3])
            kinds = [k for k in KIND_FA if k != "stub"]
            kind = mid[0].selectbox("نوع", kinds, format_func=lambda k: KIND_FA[k])
            title = mid[1].text_input("عنوان ماده", placeholder="یک عنوان کوتاه برای ماده")
            text = st.text_area("متن ماده", height=140)
            keywords = st.text_input("کلیدواژه‌ها (با ویرگول جدا کنید)")
            if st.form_submit_button("ثبت ماده", type="primary"):
                if not law_title.strip() or not text.strip():
                    st.warning("عنوان قانون و متن ماده لازم است.")
                else:
                    try:
                        ref = aio.run(_add({
                            "law_title": law_title.strip(), "law_year": law_year.strip() or None,
                            "article_no": article_no.strip() or None, "kind": kind,
                            "title": title.strip() or None, "text": text.strip(),
                            "keywords": split_list(keywords),
                        }))
                    except Exception as error:  # noqa: BLE001
                        components.error_box(error)
                    else:
                        data.refresh()
                        st.session_state["law_focus"] = ref["id"]
                        st.success(f"ثبت شد: {ref['cite']}")
                        st.rerun()


def render(cfg: dict, state: dict) -> None:
    st.title("قوانین و مستندات")
    st.caption("مواد قانونی، آیین‌نامه‌ها و آرای وحدت رویه‌ای که پرونده‌های آرشیو به آن‌ها استناد کرده‌اند.")

    # A focus handed over from a case: open its law, and put the article first.
    focus = None
    if st.session_state.get("law_focus"):
        try:
            focus = aio.run(_ref(st.session_state["law_focus"]))
        except Exception as error:  # noqa: BLE001
            components.error_box(error)
        if focus:
            st.session_state["law_title_sel"] = focus["law_title"]
        else:
            st.session_state["law_focus"] = None

    query = st.text_input(
        "جستجو", key="laws_q", label_visibility="collapsed",
        placeholder="جستجو در متن مواد، یا مستقیم: ماده ۳۰ قانون بیمه",
    )

    if query and query.strip():
        try:
            with st.spinner("در حال جستجو…"):
                hits = aio.run(_search(query))
        except Exception as error:  # noqa: BLE001
            components.error_box(error)
            return
        st.caption(f"{fa_num(len(hits))} ماده برای «{query.strip()}»")
        if not hits:
            components.empty("مادهٔ مرتبطی یافت نشد.")
        for ref in hits:
            _article_card(ref)
        _add_form("")
        return

    titles = state.get("law_titles") or []
    selected = st.session_state.get("law_title_sel")
    if selected and selected not in {t["law_title"] for t in titles}:
        selected = None
        st.session_state["law_title_sel"] = None

    main, side = st.columns([5, 2], gap="medium")

    with side:
        st.markdown("<div class='panel-title'>قوانین</div>", unsafe_allow_html=True)
        if st.button(
            f"همهٔ قوانین ({fa_num(sum(t['articles'] for t in titles))})",
            key="lt_all", use_container_width=True,
            type="primary" if not selected else "secondary",
        ):
            st.session_state["law_title_sel"] = None
            st.session_state["law_focus"] = None
            st.rerun()
        for index, t in enumerate(titles):
            label = f"{t['law_title']}" + (f" ({fa_num(t['law_year'])})" if t.get("law_year") else "")
            label += f"  ·  {fa_num(t['articles'])} ماده"
            if t.get("kind") == "stub":
                label += " · حل‌نشده"
            if st.button(
                label, key=f"lt_{index}", use_container_width=True,
                type="primary" if t["law_title"] == selected else "secondary",
            ):
                st.session_state["law_title_sel"] = t["law_title"]
                st.session_state["law_focus"] = None
                st.rerun()

    with main:
        try:
            articles = aio.run(_articles(selected))
        except Exception as error:  # noqa: BLE001
            components.error_box(error)
            return

        stubs = [a for a in articles if a.get("kind") == "stub"]
        articles = [a for a in articles if a.get("kind") != "stub"]
        if focus:
            articles = [focus] + [a for a in articles if a["id"] != focus["id"]]

        st.caption(
            (f"{esc(selected)} · " if selected else "همهٔ قوانین · ")
            + f"{fa_num(len(articles))} ماده"
            + (f" · نمایش {fa_num(_PAGE)} مادهٔ اول" if len(articles) > _PAGE else "")
        )
        if not articles and not stubs:
            components.empty("مادهٔ قانونی ثبت نشده است.")
        for ref in articles[:_PAGE]:
            _article_card(ref, focused=bool(focus and ref["id"] == focus["id"]))

        if stubs:
            st.divider()
            st.subheader("ارجاع‌های حل‌نشده")
            st.warning(
                f"{fa_num(len(stubs))} ارجاع به ماده‌ای است که متنش در پایگاه قوانین نیست. "
                "با «افزودن مادهٔ جدید» و همان عنوان و شمارهٔ ماده، ارجاع حل می‌شود."
            )
            for ref in stubs:
                _article_card(ref)

        _add_form(selected or "")

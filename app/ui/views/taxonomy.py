"""۰۸ طبقه‌بندی و برچسب‌ها — the tag vocabulary and what each tag covers."""

import streamlit as st

from app.rag import catalog
from app.rag.taxonomy import TAXONOMY
from app.ui import aio, components
from app.ui.resources import session
from app.ui.theme import card, chips, esc, fa_num


async def _tags() -> list[dict]:
    async with session() as s:
        return await catalog.list_labels(s, kind="tag", limit=500)


def render(cfg: dict, state: dict) -> None:
    st.title("طبقه‌بندی و برچسب‌ها")
    st.caption(
        "برچسب‌ها از استخراج ساختاریافته می‌آیند. برای دیدن پرونده‌های یک برچسب "
        "روی «پرونده‌ها» کنار آن بزنید."
    )

    tags = state["tags"]
    if not tags:
        components.empty("هنوز برچسبی استخراج نشده است.")
        return

    cols = st.columns(3)
    cols[0].metric("برچسب‌های یکتا", fa_num(len(tags)))
    cols[1].metric("پرکاربردترین", tags[0]["tag"] if tags else "—")
    cols[2].metric("پرونده‌های برچسب‌خورده", fa_num(sum(1 for c in state["cases"] if c["tags"])))

    st.divider()
    st.subheader("تاکسونومی پایه")
    st.caption("واژگان پیشنهادی که خط لولهٔ ساخت مدخل برای برچسب‌گذاری از آن استفاده می‌کند.")
    corpus = {t["tag"] for t in tags}
    for root in TAXONOMY:
        blocks = ""
        for group in root["categories"]:
            leaves = "".join(
                f"<span class='chip{' teal' if leaf in corpus else ''}'>{esc(leaf)}"
                f"{' ·' if leaf in corpus else ''}</span>"
                for leaf in group["leaves"]
            )
            blocks += (
                f"<div style='margin-top:8px'><b style='font-size:12px'>{esc(group['name'])}</b>"
                f"<div style='margin-top:4px'>{leaves}</div></div>"
            )
        card(f"<h4>{esc(root['root'])}</h4>{blocks}")
    st.caption("برچسب‌های تیره‌رنگ در آرشیو استفاده شده‌اند.")

    st.divider()
    st.subheader("همهٔ برچسب‌ها")

    components.rowlist_start()
    for tag in tags:
        if components.row(
            tag["tag"], f"{fa_num(tag['cases'])} پرونده", key=f"tax_{tag['tag']}"
        ):
            # The tag was extracted from the entries, so open its cases
            # directly rather than sending the user to a search box.
            st.session_state["open_name"] = tag["tag"]
            st.session_state["view"] = "analytics"
            st.rerun()

    st.divider()
    st.subheader("موضوعات و مراجع")
    topics, courts = set(), set()
    for case in state["cases"]:
        topics.update(str(t) for t in case["topics"])
        if case["court"] and case["court"] != "—":
            courts.add(str(case["court"]))
    left, right = st.columns(2)
    with left:
        st.caption("موضوعات")
        card(chips(sorted(topics)))
    with right:
        st.caption("مراجع رسیدگی")
        card(chips(sorted(courts), teal=True))

    st.divider()
    st.subheader("برچسب‌های دستی ثبت‌شده")
    try:
        manual = aio.run(_tags())
    except Exception as error:  # noqa: BLE001
        components.error_box(error)
        return
    if manual:
        st.dataframe(manual, use_container_width=True, hide_index=True)
    else:
        components.empty("برچسب دستی ثبت نشده است.")

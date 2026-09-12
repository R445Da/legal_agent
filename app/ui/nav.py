"""
The numbered sections, in a collapsible rail on the right.

Two panels, mirroring each other: the model and retrieval settings sit on the
left in Streamlit's own sidebar with its native » / « control, and this rail sits
on the right with a chevron of its own. Nothing runs across the top.

It has to be a column rather than a second `st.sidebar` because Streamlit only
has one. Because the horizontal block reads right to left, the first column is
the rightmost — which is where this belongs.

Section ids and Persian labels here are how the user refers to screens.
"""

import streamlit as st

from app.ui import theme
from app.ui.theme import esc, fa_num

# (id, number, Persian label)
SECTIONS = [
    ("agent", "۰۱", "دستیار پرونده"),
    ("dashboard", "۰۲", "داشبورد"),
    ("cases", "۰۳", "پرونده‌ها"),
    ("events", "۰۴", "رویدادها"),
    ("ingest", "۰۵", "بایگانی سند جدید"),
    ("search", "۰۶", "جستجو و پرسش"),
    ("documents", "۰۷", "تیکت‌ها (اسناد)"),
    ("taxonomy", "۰۸", "طبقه‌بندی و برچسب‌ها"),
    ("review", "۰۹", "بازبینی انسانی"),
    ("labeling", "۱۰", "برچسب‌گذاری و بازخورد"),
    ("analytics", "۱۱", "آمار آرشیو"),
    ("schema", "۱۲", "ساختار داده و خط لوله"),
    ("eval", "۱۳", "ارزیابی بازیابی"),
    ("bench", "۱۴", "مقایسهٔ مدل‌ها"),
]

_LABELS = {sid: (num, label) for sid, num, label in SECTIONS}


def current() -> str:
    return st.session_state.setdefault("view", "agent")


def go(view: str, **params) -> None:
    """Navigate, carrying any parameters (the case or document being opened)."""
    st.session_state["view"] = view
    for key, value in params.items():
        st.session_state[key] = value
    st.rerun()


def title_of(view: str) -> str:
    num, label = _LABELS.get(view, ("", view))
    return f"{num} · {label}" if num else label


def expanded() -> bool:
    return st.session_state.setdefault("show_nav", True)


def render(state: dict) -> str:
    """Draw the rail; return the active section id."""
    active = current()
    is_open = expanded()
    review_count = len(state.get("review_queue", []))

    # The marker is what the stylesheet keys on to paint this column as the
    # rail and to pin its width.
    st.markdown(
        f"<div class='nav-rail{'' if is_open else ' shut'}'></div>",
        unsafe_allow_html=True,
    )

    # Separate keys per state: Streamlit stamps `st-key-<key>` on the element,
    # which gives the stylesheet an unambiguous hook for the collapsed handle.
    if st.button("«" if is_open else "»",
                 key="nav_toggle_open" if is_open else "nav_toggle_shut",
                 help="باز و بسته کردن فهرست بخش‌ها"):
        st.session_state["show_nav"] = not is_open
        st.rerun()

    if not is_open:
        return active

    st.markdown("<div class='rail-brand'>آرشیو حقوقی</div>", unsafe_allow_html=True)
    counts = state["counts"]
    st.caption(
        f"{fa_num(counts['documents'])} سند · {fa_num(counts['chunks'])} قطعه · "
        f"{fa_num(counts['entries'])} مدخل"
    )

    for sid, num, label in SECTIONS:
        badge = review_count if sid == "review" and review_count else 0
        if sid == active:
            st.markdown(
                f"<div class='nav-item active'><span class='n'>{num}</span>"
                f"<span>{esc(label)}</span>"
                + (f"<span class='nav-badge'>{fa_num(badge)}</span>" if badge else "")
                + "</div>",
                unsafe_allow_html=True,
            )
            continue
        text = f"{num}  {label}" + (f"   ({fa_num(badge)})" if badge else "")
        if st.button(text, key=f"nav_{sid}", use_container_width=True):
            go(sid, open_case=None, open_doc=None)

    dark = theme.current() == "dark"
    if st.button("☀  حالت روشن" if dark else "🌙  حالت تیره",
                 key="nav_theme", use_container_width=True):
        theme.toggle()
        st.rerun()

    return active

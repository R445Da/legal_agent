"""Shared presentation pieces, so every screen renders an answer the same way."""

import streamlit as st

from app.ui.theme import card, esc, fa_num


def reasoning_panel(text: str | None, *, key: str = "", expanded: bool = False) -> None:
    """The «استدلال مدل» panel — created only when there is reasoning to show.

    Plain chat models return `reasoning=None`, and then no panel exists at all
    rather than an empty box. It renders collapsed: by the time a non-streaming
    response is in hand the answer is already available, so the
    expand-while-thinking behaviour belongs to a future streaming path.
    """
    if not text:
        return
    with st.expander("استدلال مدل", expanded=expanded):
        st.markdown(
            "<div style='font-size:.88em;opacity:.85;white-space:pre-wrap;line-height:2'>"
            f"{esc(text)}</div>",
            unsafe_allow_html=True,
        )


def steps_panel(steps: list[dict], *, title: str = "خط لوله") -> None:
    """The pipeline trace the orchestrator and RAG pipeline already emit."""
    if not steps:
        return
    with st.expander(title):
        for step in steps:
            ms = step.get("ms")
            suffix = f" · {fa_num(ms)} میلی‌ثانیه" if ms is not None else ""
            st.markdown(
                f"<div class='kv'><span class='k'>{esc(step.get('name',''))}{suffix}</span>"
                f"<span>{esc(step.get('detail',''))}</span></div>",
                unsafe_allow_html=True,
            )


def citations(
    contexts: list[dict], *, document_action: bool = False, expanded: bool = False,
    key_prefix: str = ""
) -> dict | None:
    """The retrieved excerpts, in citation order, matching the [n] in the answer."""
    if not contexts:
        st.info("قطعه‌ای بازیابی نشد — شاید آرشیو برای این دامنه خالی است.")
        return None
    st.caption(f"{fa_num(len(contexts))} قطعهٔ استنادشده")
    for ctx in contexts:
        title = ctx.get("title") or ctx.get("source") or "—"
        score = ctx.get("similarity")
        head = f"[{fa_num(ctx['n'])}] {title}" + (f"  ·  {fa_num(f'{score:.3f}')}" if score is not None else "")
        with st.expander(head, expanded=expanded):
            st.caption(ctx.get("source", ""))
            st.markdown(
                f"<div style='white-space:pre-wrap;line-height:2'>{esc(ctx.get('text',''))}</div>",
                unsafe_allow_html=True,
            )
            if document_action and ctx.get("document_id"):
                if st.button(
                    "باز کردن متن کامل سند",
                    key=f"open_source_{key_prefix}_{ctx['n']}_{ctx['document_id']}",
                ):
                    return ctx
    return None


def usage_caption(*, model: str, input_tokens=None, output_tokens=None) -> None:
    bits = [f"`{model}`"]
    if input_tokens is not None:
        bits.append(f"ورودی {fa_num(input_tokens)}")
    if output_tokens is not None:
        bits.append(f"خروجی {fa_num(output_tokens)}")
    st.caption(" · ".join(bits) + " توکن")


def error_box(error: Exception) -> None:
    """Provider errors carry the actionable detail (truncation, missing key,
    unreachable gateway) — show the message, not a stack trace."""
    st.error(f"**{type(error).__name__}** — {error}")


def row(title: str, *lines: str, key: str, kind: str = "") -> bool:
    """A whole record rendered as one clickable row.

    The old UI opened a case or a document by clicking the record itself; a
    separate «مشاهده» button beside every card was both noise and the reason
    lists had ragged left edges (the row had to be split into columns just to
    hold the button). Here the row *is* the control: a full-width button
    styled as a ledger card by `.rowlist` in theme.py.

    Streamlit button labels take Markdown but not HTML, so the supporting
    detail is passed as extra `lines` joined with a hard line break rather
    than as chips.
    """
    # Streamlit renders Markdown in a button label, so the title can carry
    # weight and the supporting lines can be greyed with :gray[…]. Without that
    # every line landed at the same size and the row read as a wall of text.
    body = "  \n".join(f":gray[{line}]" for line in lines if line)
    label = f"**{title}**" + (f"  \n{body}" if body else "")
    return st.button(label, key=key, use_container_width=True, type=kind or "secondary")


def rowlist_start() -> None:
    """Marks the following buttons as clickable record rows."""
    st.markdown("<div class='rowlist'></div>", unsafe_allow_html=True)


def empty(message: str) -> None:
    card(f"<div class='meta' style='text-align:center;padding:18px'>{esc(message)}</div>")

"""Shared presentation pieces, so every screen renders an answer the same way."""

import streamlit as st

from app.ui.theme import card, esc, fa_num, stamp

_GROUNDING_FA = {"ok": ("مستند", "teal"), "partial": ("استناد ناقص", "gold"),
                 "unsupported": ("بدون استناد", "review")}


def provenance_panel(prov: dict | None, *, key_prefix: str = "", expanded: bool = False) -> None:
    """What the answer rests on: the citation check, the numbered evidence,
    the tool trail and the token bill — one panel for every route."""
    if not prov:
        return
    grounding = prov.get("grounding") or {}
    status = grounding.get("status", "unsupported")
    label, kind = _GROUNDING_FA.get(status, ("—", "gray"))
    evidence = prov.get("evidence") or []
    trail = prov.get("tool_trail") or []
    usage = prov.get("usage") or {}
    coverage = grounding.get("coverage")

    bits = [stamp(label, kind)]
    if coverage is not None:
        bits.append(f"<span class='meta'>پوشش استناد {fa_num(round(coverage * 100))}٪</span>")
    bits.append(f"<span class='meta'>{fa_num(len(evidence))} شاهد</span>")
    if trail:
        bits.append(f"<span class='meta'>{fa_num(len(trail))} فراخوانی ابزار</span>")
    if usage.get("cache_read_tokens"):
        bits.append(f"<span class='meta'>خواندن از حافظهٔ نهان {fa_num(usage['cache_read_tokens'])}</span>")
    st.markdown("<div class='prov-bar'>" + " · ".join(bits) + "</div>", unsafe_allow_html=True)

    with st.expander("شواهد و ردپای پاسخ", expanded=expanded):
        if grounding.get("invalid"):
            st.warning("ارجاع به شمارهٔ ناموجود: " + "، ".join(f"[{fa_num(n)}]" for n in grounding["invalid"]))
        for item in evidence:
            score = item.get("score")
            head = f"[{fa_num(item.get('n', ''))}] {esc(item.get('label') or item.get('title') or '')}"
            tail = f"{fa_num(f'{score:.2f}')}" if isinstance(score, (int, float)) else ""
            st.markdown(f"<div class='kv'><span class='k'>{head}</span><span>{tail}</span></div>",
                        unsafe_allow_html=True)
        unsupported = grounding.get("unsupported_claims") or []
        if unsupported:
            st.markdown("<div class='meta' style='margin-top:6px'>جمله‌های بدون استناد:</div>", unsafe_allow_html=True)
            for claim in unsupported[:6]:
                st.markdown(f"<div class='meta'>• {esc(claim.get('text', ''))[:200]}</div>", unsafe_allow_html=True)
        if trail:
            st.markdown("<div class='meta' style='margin-top:6px'>ردپای ابزارها:</div>", unsafe_allow_html=True)
            for row in trail:
                ms = row.get("ms")
                suffix = f" · {fa_num(ms)} میلی‌ثانیه" if ms is not None else ""
                st.markdown(
                    f"<div class='kv'><span class='k mono'>{esc(row.get('tool', ''))}{suffix}</span>"
                    f"<span>{esc(row.get('summary', ''))}</span></div>",
                    unsafe_allow_html=True,
                )
        if usage:
            usage_caption(
                model=prov.get("model") or "—", input_tokens=usage.get("input_tokens"),
                output_tokens=usage.get("output_tokens"),
                cache_read_tokens=usage.get("cache_read_tokens"),
            )


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


def usage_caption(*, model: str, input_tokens=None, output_tokens=None, cache_read_tokens=None) -> None:
    bits = [f"`{model}`"]
    if input_tokens is not None:
        bits.append(f"ورودی {fa_num(input_tokens)}")
    if output_tokens is not None:
        bits.append(f"خروجی {fa_num(output_tokens)}")
    if cache_read_tokens:
        bits.append(f"حافظهٔ نهان {fa_num(cache_read_tokens)}")
    st.caption(" · ".join(bits) + " توکن")


def similar_cases_panel(
    items: list[dict] | None, lessons: dict | None = None, advice: str | None = None,
    *, key_prefix: str = "", offset: int = 0,
) -> str | None:
    """«پرونده‌های مشابه در بایگانی»: each case as a clickable row with its
    match bar and the reasons it resembles the question, the outcome tally,
    and the comparative paragraph. Returns the case number that was clicked."""
    if not items:
        return None
    from app.ui.theme import chips

    clicked = None
    with st.expander(f"پرونده‌های مشابه در بایگانی ({fa_num(len(items))})", expanded=True):
        if lessons and lessons.get("summary"):
            st.caption("سرنوشت پرونده‌های مشابه: " + lessons["summary"])
        rowlist_start()
        for i, c in enumerate(items, offset + 1):
            score = c.get("score") or 0.0
            pct = max(0, min(100, round(float(score) * 100 / 1.5)))
            head = f"[{fa_num(i)}] {c.get('title') or c.get('case_number')}"
            line1 = (f"شماره {fa_num(c.get('case_number', ''))} · {c.get('case_type') or '—'} · "
                     f"{c.get('status_fa') or ''} · شباهت {fa_num(pct)}٪")
            line2 = (c.get("outcome") or "")[:110] or None
            if row(head, line1, line2, key=f"sim_{key_prefix}_{i}_{c.get('id')}"):
                clicked = c.get("case_number")
            why = c.get("why") or []
            if why:
                st.markdown(chips(why[:4], teal=True), unsafe_allow_html=True)
            for path in (c.get("path") or [])[:2]:
                crumbs = []
                for node in path:
                    if "relation" in node and "type" not in node:
                        crumbs.append(f"—{esc(node.get('relation_fa', ''))}→")
                    else:
                        crumbs.append(esc(node.get("label") or node.get("id", "")[:8]))
                st.markdown(f"<div class='meta mono' style='direction:rtl'>{' '.join(crumbs)}</div>",
                            unsafe_allow_html=True)
        if lessons:
            cols = st.columns(2)
            with cols[0]:
                st.markdown("<div class='meta'><b>چه چیزی جواب داد</b></div>", unsafe_allow_html=True)
                for item in (lessons.get("worked") or [])[:4]:
                    st.markdown(f"<div class='meta'>✓ {esc(item.get('case_number', ''))}"
                                f"{' — ' + esc(item['point']) if item.get('point') else ''}</div>", unsafe_allow_html=True)
                if not lessons.get("worked"):
                    st.markdown("<div class='meta'>—</div>", unsafe_allow_html=True)
            with cols[1]:
                st.markdown("<div class='meta'><b>چه چیزی جواب نداد</b></div>", unsafe_allow_html=True)
                for item in (lessons.get("failed") or [])[:4]:
                    st.markdown(f"<div class='meta'>✕ {esc(item.get('case_number', ''))}"
                                f"{' — ' + esc(item['point']) if item.get('point') else ''}</div>", unsafe_allow_html=True)
                if not lessons.get("failed"):
                    st.markdown("<div class='meta'>—</div>", unsafe_allow_html=True)
        if advice:
            st.markdown("<div class='meta' style='margin-top:8px'><b>تحلیل تطبیقی</b></div>", unsafe_allow_html=True)
            st.markdown(f"<div class='answer'>{esc(advice)}</div>", unsafe_allow_html=True)
    return clicked


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

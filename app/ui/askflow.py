"""
How one question of the filing dialogue looks.

The dialogue itself — the queue, the cursor, what an answer means — lives in
`app/rag/conversation.py` and is persisted in the run state, so a reload or
the API resumes on the same question. This module is only its face: it turns
a question's `card` spec into the ledger vocabulary the rest of the app is
drawn in, and nothing here knows what happens next.

The split matters. An earlier version kept the whole state machine in
`st.session_state`, which made the conversation a property of one browser tab:
a reload lost it, and the API could not see it at all. Keeping presentation
here and state there is what lets the same dialogue be driven from the chat,
from section ۰۵, or over HTTP.

A card spec is `{"kind": ..., "data": ...}`:

    value        a single field's text
    case_number  the docket, one bordered box per digit
    refs         the citations, each with its «متصل» / «بدون اتصال» stamp
    timeline     the events, on the vertical timeline
    similar      matched prior records with their outcome
    labels       the proposed tags as chips
"""

from __future__ import annotations

from app.ui.theme import case_id, chips as chip_html, esc, fa_num, timeline as tl_html


def _wrap(body: str) -> str:
    return f"<div class='ask-card'>{body}</div>"


def _refs_card(rows: list[dict]) -> str:
    items = []
    for row in rows or []:
        cite = row.get("law") or ""
        if row.get("article"):
            cite = f"مادهٔ {fa_num(row['article'])} {cite}"
        linked = ("<span class='stamp teal'><span class='dotc'></span>متصل</span>"
                  if row.get("resolved") else
                  "<span class='stamp review'><span class='dotc'></span>بدون اتصال</span>")
        items.append(f"<div class='ask-row'><span>{esc(cite)}</span>{linked}</div>")
    return _wrap("".join(items))


def _similar_card(rows: list[dict]) -> str:
    from app.rag.casebase import STATUS_FA

    items = []
    for row in rows or []:
        # `outcome` is Persian prose for most rows, but a matched entry whose
        # only recorded outcome is its status carries the schema's English
        # enum — translate rather than print `closed` in a Persian sentence.
        outcome = (row.get("outcome") or "").strip()
        outcome = STATUS_FA.get(outcome, outcome)
        items.append(
            f"<div class='ask-row'><span>{esc(row.get('title') or 'بدون عنوان')}</span>"
            f"<span class='meta'>{esc(outcome[:60])}</span></div>"
        )
    return _wrap("".join(items))


def card_html(card: dict | None) -> str:
    """The value under discussion, or "" when the question stands alone."""
    if not card:
        return ""
    kind, data = card.get("kind"), card.get("data")
    if kind == "value":
        return _wrap(f"<div class='ask-value'>{esc(data)}</div>")
    if kind == "case_number":
        return _wrap(case_id(data))
    if kind == "refs":
        return _refs_card(data or [])
    if kind == "timeline":
        return _wrap(tl_html(data or []))
    if kind == "similar":
        return _similar_card(data or [])
    if kind == "labels":
        return _wrap(chip_html(data, teal=True) if data
                     else "<div class='meta'>برچسبی پیشنهاد نشد.</div>")
    return ""


def question_html(question: dict, *, step: int = 0, total: int = 0) -> str:
    """One question, ready for `st.markdown(..., unsafe_allow_html=True)`."""
    counter = (f"<span class='ask-count'>پرسش {fa_num(step)} از {fa_num(total)}</span>"
               if total else "")
    note = (f"<div class='ask-note'>{esc(question.get('note'))}</div>"
            if question.get("note") else "")
    return (f"<div class='ask'>{counter}"
            f"<div class='ask-q'>{esc(question.get('prompt', ''))}</div>"
            f"{card_html(question.get('card'))}{note}</div>")

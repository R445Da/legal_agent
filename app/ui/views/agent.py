"""
۰۱ دستیار پرونده — the chat.

This is a conversation, not a form. One composer at the bottom holds both the
microphone and the text box, the transcript stays above it, and the answer
streams in token by token rather than appearing all at once when the model
finishes.

Speaking and typing are the same act: a recording is transcribed and then sent
as the message, so there is no separate "voice mode" to switch into and no
button to press afterwards.

The router still decides what each message is — a question to answer from the
archive, new material to file, or a request for statistics — and the archive
path keeps its draft in `st.session_state` until the user confirms it, because
nothing may be written to the archive without that confirmation.
"""

import datetime as dt

import streamlit as st
from sqlalchemy import or_, select

from app.db.models import Entry
from app.rag import runs, transcribe as stt, workflow
from app.rag.orchestrator import _INTENT_FA, corpus_stats, route
from app.rag.ingest import get_document
from app.rag.pipeline import SYSTEM_PROMPT, build_prompt, format_source, snippet
from app.rag.catalog import search_entries
from app.rag.retriever import retrieve_scored
from app.rag.textnorm import normalize_fa
from app.ui import aio, askflow, components, data
from app.ui.resources import session
from app.ui.theme import card, case_id, chips, esc, fa_num, kv, stamp

_EXAMPLES = [
    "ماده ۳۰ قانون بیمه دربارهٔ جانشینی چه می‌گوید؟",
    "پرونده‌های بازیافت از رانندهٔ فاقد گواهینامه چطور تمام شده‌اند؟",
    "وکیل رضا کریمی در چه پرونده‌هایی بوده؟",
    "چند پرونده شخص ثالث داریم؟",
]


def _history() -> list[dict]:
    return st.session_state.setdefault("chat", [])


def _say(role: str, **fields) -> dict:
    message = {"role": role, **fields}
    _history().append(message)
    return message


# --------------------------------------------------------------------------- #
# The three things a message can turn into
# --------------------------------------------------------------------------- #
def _answer_from_archive(cfg: dict, text: str) -> None:
    """Retrieve, then stream the grounded answer into the open bubble."""
    trace: dict = {}

    async def _retrieve():
        async with session() as s:
            rows = await retrieve_scored(
                s, text, top_k=cfg["top_k"], trace=trace, **cfg["retrieval"]
            )
            # Entries are matched on how *rare* a question's words are in the
            # archive, not on a hand-written stoplist — see
            # `catalog.search_entries`. A list of words to ignore never keeps up:
            # «تصمیمی» matched no entry and «گرفت» matched half of them, so the
            # one word that identified the case was drowned out.
            matched_entries = await search_entries(s, text)
            tokens = [
                token.strip("؟?.,،:؛«»\"'")
                for token in normalize_fa(text).split()
            ]
            tokens = [token for token in tokens if len(token) >= 3]
            return [
                {
                    "n": i + 1,
                    "title": c.document.title or c.document.source,
                    "source": c.document.source,
                    "document_id": str(c.document_id),
                    "similarity": round(1 - d, 3),
                    "text": c.text,
                }
                for i, (c, d) in enumerate(rows)
            ], matched_entries, tokens, build_prompt(text, [c for c, _ in rows])

    with st.status("در حال جستجو در آرشیو…", expanded=False) as status:
        contexts, matched_entries, entry_terms, prompt = aio.run(_retrieve())
        status.update(
            label=f"{fa_num(len(contexts))} قطعه بازیابی شد "
                  f"({fa_num(round(sum(trace.get(k, 0) for k in ('vector_ms','lexical_ms','rerank_ms'))))} میلی‌ثانیه)",
            state="complete",
        )

    if matched_entries:
        with st.expander(f"مدخل‌های پیدا‌شده ({fa_num(len(matched_entries))})", expanded=True):
            for entry in matched_entries:
                title = entry.title or "بدون عنوان"
                # Plain Markdown here, so the text must NOT be HTML-escaped:
                # esc() turns "<" into "&lt;" and "&" into "&amp;", and without
                # unsafe_allow_html those entities render literally — which is
                # the raw HTML that was showing up in the panel.
                st.markdown(
                    f"**{title}**  \n"
                    f"{entry.summary or 'خلاصه‌ای ثبت نشده است.'}  \n"
                    f"`{entry.kind or 'session'}`"
                )
        # The structured entries have to enter the prompt as *numbered excerpts*,
        # continuing the same [n] sequence as the retrieved chunks. The system
        # prompt tells the model to answer only from the numbered excerpts and to
        # cite a bracket number for every claim, so anything supplied outside
        # that numbering is correctly ignored — which is why questions like
        # "show me Mr Karimi's cases" were answered with "excerpts [1]–[5]
        # contain nothing about him" even though eight entries mentioned him.
        entry_blocks = []
        for entry in matched_entries:
            parties = "، ".join(
                line for line in map(_label_party, entry.parties or []) if line
            )
            meta = "، ".join(part for part in (
                f"طرفین: {parties}" if parties else "",
                f"مشخصات: {entry.entities}" if entry.entities else "",
            ) if part)
            # Include the passage that actually matched. Entries are searched
            # against their raw text, so a record can match on something buried
            # in the body while its title and summary never mention it — which
            # made correct answers look like they cited unrelated cases.
            body = "\n".join(part for part in (
                entry.summary or "",
                snippet(entry.raw_text or "", entry_terms),
            ) if part.strip())
            entry_blocks.append(format_source(
                kind="مدخل", title=entry.title or "بدون عنوان", body=body, meta=meta,
            ))
        # Entries first: they are the structured record and answer relational
        # questions ("which cases involve X") that chunk search cannot.
        chunk_blocks = [
            format_source(kind="سند", title=c["title"], body=c["text"])
            for c in contexts
        ]
        prompt = build_prompt(text, entry_blocks + chunk_blocks)
        for offset, entry in enumerate(matched_entries, start=1):
            contexts.insert(
                offset - 1,
                {
                    "n": offset,
                    "title": entry.title or "مدخل بدون عنوان",
                    "source": f"entry/{entry.id}",
                    "document_id": str(entry.document_id) if entry.document_id else None,
                    "similarity": None,
                    "text": entry_blocks[offset - 1],
                },
            )
        for i, ctx in enumerate(contexts, start=1):
            ctx["n"] = i

    with st.expander(f"متن بازیابی‌شده ({fa_num(len(contexts))} قطعه)", expanded=True):
        components.citations(
            contexts, document_action=True, expanded=True, key_prefix="live"
        )

    thinking = st.empty()
    thoughts: list[str] = []
    answer_box = st.empty()
    answer: list[str] = []
    final = None

    stream = _active_llm(cfg).stream(
        prompt, system=SYSTEM_PROMPT, max_tokens=cfg["max_tokens"], **cfg["knobs"]
    )
    collapsed = False
    for event in aio.iterate(stream):
        if event["type"] == "reasoning":
            thoughts.append(event["delta"])
            thinking.markdown(
                "<div class='thinking'><b>در حال استدلال…</b><br>"
                f"{esc(''.join(thoughts))[-700:]}</div>",
                unsafe_allow_html=True,
            )
        elif event["type"] == "answer":
            # Collapse the thinking panel once, on the first answer token —
            # not on every one of them.
            if thoughts and not collapsed:
                collapsed = True
                thinking.markdown(
                    f"<details class='thinking'><summary>استدلال مدل</summary>"
                    f"<div>{esc(''.join(thoughts))}</div></details>",
                    unsafe_allow_html=True,
                )
            answer.append(event["delta"])
            answer_box.markdown(
                f"<div class='answer'>{esc(''.join(answer))}</div>", unsafe_allow_html=True
            )
        elif event["type"] == "done":
            final = event["response"]

    text_out = "".join(answer)
    if not text_out.strip():
        # The model reasoned and then stopped without writing an answer. Say so
        # rather than storing an empty bubble that reads as the reply vanishing.
        # On a reasoning model the token budget covers the hidden thinking *and*
        # the answer, so this usually means the budget ran out while thinking.
        thinking.markdown(
            f"<details class='thinking' open><summary>استدلال مدل</summary>"
            f"<div>{esc(''.join(thoughts))}</div></details>",
            unsafe_allow_html=True,
        )
        answer_box.warning(
            "مدل فقط استدلال کرد و پاسخی ننوشت. سقف توکن خروجی شامل استدلال "
            "پنهان و خودِ پاسخ است؛ «سقف توکن خروجی» را بالا ببرید یا «میزان "
            "استدلال» را کم کنید."
        )

    _say(
        "assistant", intent="query", text=text_out,
        reasoning="".join(thoughts) or None,
        contexts=contexts, trace=trace,
        model=final.model if final else cfg["model_id"],
        latency_ms=final.latency_ms if final else None,
    )


# --------------------------------------------------------------------------- #
# The archive path is a pipeline now (app/rag/workflow.py): classify → extract →
# timeline → similar → labels → commit, pausing at each gate for the user. The
# run is persisted, so a reload or a model failure never loses a step or the
# text, and the build console at :8000/runs/view shows the same steps.
# --------------------------------------------------------------------------- #
def _wf_start(cfg: dict, text: str, source: str, *, mode: str, forced: str | None) -> dict:
    async def _go():
        async with session() as s:
            return await workflow.start(
                s, raw_text=text, source=source, llm=cfg["llm"],
                mode=mode, forced_intent=forced,
            )
    return aio.run(_go())


def _wf_advance(cfg: dict, run_id: str, user_patch: dict | None = None) -> dict:
    async def _go():
        async with session() as s:
            return await workflow.advance(s, run_id, cfg["llm"], user_patch=user_patch)
    return aio.run(_go())


def _wf_load(run_id: str) -> dict | None:
    async def _go():
        async with session() as s:
            return await runs.load_run(s, run_id)
    return aio.run(_go())


def _wf_abandon(run_id: str) -> None:
    async def _go():
        async with session() as s:
            await runs.set_status(s, run_id, "abandoned")
    aio.run(_go())


def _draft_for_archive(
    cfg: dict, text: str, *, source: str | None = None, forced: str | None = None,
) -> None:
    source = source or f"assistant/{dt.datetime.now():%Y%m%d-%H%M%S}"
    mode = st.session_state.get("wf_mode", "review")
    spinner = {
        "review": "در حال استخراج مدخل — یک بار برای بازبینی می‌ایستد…",
        "steps": "در حال آغاز خط لوله — گام‌به‌گام…",
        "auto": "در حال استخراج و ثبت خودکار مدخل…",
    }.get(mode, "در حال آغاز خط لوله…")
    with st.status(spinner, expanded=False) as status:
        view = _wf_start(cfg, text, source, mode=mode, forced=forced)
        if view["status"] == "committed":
            status.update(label="مدخل ثبت شد", state="complete")
        else:
            awaiting = next((s for s in view["steps"] if s["status"] == "awaiting_input"), None)
            status.update(
                label="آمادهٔ گفتگو" if awaiting else "خط لوله آغاز شد",
                state="complete",
            )
    # The run's own turn in the transcript: the step rail and the record as it
    # stands. The questions that follow are separate turns, so the transcript
    # reads as a conversation rather than as one panel that keeps changing.
    _say("assistant", intent="archive", run_id=view["id"])
    _after_advance(cfg, view)


# --------------------------------------------------------------------------- #
# The gate as a conversation (app/ui/askflow.py)
#
# A gate used to be a panel: every field of the record at once, as editable
# grids, with one «تأیید و ادامه» button. Now the same payload becomes an
# ordered list of questions, and the chat asks them one at a time — the answer
# to each is its own turn, typed in the composer or tapped from a quick reply.
# The workflow underneath is untouched: only when the last question is answered
# does a single `user_patch` go back to `workflow.advance`.
# --------------------------------------------------------------------------- #
def _ask_next(run_id: str) -> None:
    """Post the question the conversation is now on, as an assistant turn."""
    question = askflow.current()
    if question is None:
        return
    step, total = askflow.progress()
    _say(
        "assistant", kind="ask", run_id=run_id, qid=question["id"],
        prompt=question["prompt"], card=question.get("card", ""),
        chips=list(question.get("chips") or []), note=question.get("note", ""),
        step=step, total=total,
    )


def _close_live_question() -> None:
    """Mark the question the user just answered as no longer awaiting a reply,
    so it renders as plain transcript instead of keeping its quick replies."""
    for message in reversed(_history()):
        if message.get("kind") == "ask" and not message.get("done"):
            message["done"] = True
            return


def _after_advance(cfg: dict, view: dict) -> None:
    """Whatever the run did, say it — and if it stopped for the user, start
    asking."""
    if view["status"] == "committed":
        _say("assistant", kind="filed", run_id=view["id"], entry_id=view.get("entry_id"))
        askflow.clear()
        data.refresh()
        return

    failed = next((s for s in view["steps"] if s["status"] == "failed"), None)
    if failed:
        _say("assistant", kind="wf_failed", run_id=view["id"],
             step=failed["step_id"], error=failed.get("error") or "")
        askflow.clear()
        return

    if askflow.begin(view, mode=st.session_state.get("wf_mode", "review")):
        _ask_next(view["id"])


def _archive_turn(cfg: dict, text: str) -> None:
    """Apply the user's turn to the open question, then either ask the next one
    or hand the whole conversation back to the pipeline."""
    stt = askflow.state()
    run_id = stt["run_id"]
    _close_live_question()

    result = askflow.answer(text)
    if result["ack"]:
        _say("assistant", kind="ack", text=result["ack"])

    if result["cancelled"]:
        _wf_abandon(run_id)
        askflow.clear()
        return
    if not result["finished"]:
        _ask_next(run_id)
        return

    patch = askflow.patch()
    askflow.clear()
    with st.status("در حال ثبت مدخل…", expanded=False) as status:
        view = _wf_advance(cfg, run_id, user_patch=patch)
        status.update(
            label="مدخل ثبت شد" if view["status"] == "committed" else "گام بعدی",
            state="complete",
        )
    _after_advance(cfg, view)


def _source_preview(cfg: dict) -> None:
    document_id = st.session_state.get("source_preview")
    if isinstance(document_id, dict):
        document_id = document_id.get("document_id")
        st.session_state["source_preview"] = document_id
    if not document_id:
        return

    async def _load():
        async with session() as s:
            return await get_document(s, document_id)

    try:
        doc = aio.run(_load())
    except Exception as error:  # noqa: BLE001
        components.error_box(error)
        return
    if not doc:
        st.warning("سند پیدا نشد.")
        st.session_state.pop("source_preview", None)
        return

    with st.expander(
        f"متن کامل: {doc.get('title') or doc.get('source')}", expanded=True
    ):
        st.caption(doc.get("source", ""))
        st.markdown(
            f"<div style='white-space:pre-wrap;line-height:2'>{esc(doc.get('raw_text') or '—')}</div>",
            unsafe_allow_html=True,
        )
        if st.button("استخراج اطلاعات و ساخت مدخل", key=f"extract_source_{document_id}", type="primary"):
            st.session_state.pop("source_preview", None)
            with st.spinner("در حال استخراج اطلاعات مدخل…"):
                _draft_for_archive(cfg, doc.get("raw_text") or "", source=doc.get("source"))
            st.rerun()


def _archive_stats(cfg: dict, text: str) -> None:
    async def _go():
        async with session() as s:
            return await corpus_stats(s)

    with st.status("در حال تجمیع آمار…", expanded=False) as status:
        stats = aio.run(_go())
        status.update(label="آمار آماده شد", state="complete")

    listing = "\n".join(
        f"- {k}: {v}" for k, v in stats.items() if not isinstance(v, (list, dict))
    )
    box = st.empty()
    parts: list[str] = []
    stream = _active_llm(cfg).stream(
        f"پرسش: {text}\n\nآمار آرشیو:\n{listing}",
        system="با تکیه بر این آمار و به زبان پرسش، کوتاه پاسخ بده.",
        max_tokens=cfg["max_tokens"], **cfg["knobs"],
    )
    for event in aio.iterate(stream):
        if event["type"] == "answer":
            parts.append(event["delta"])
            box.markdown(f"<div class='answer'>{esc(''.join(parts))}</div>", unsafe_allow_html=True)

    _say("assistant", intent="analytics", text="".join(parts), stats=stats)


# --------------------------------------------------------------------------- #
# Rendering the transcript
# --------------------------------------------------------------------------- #
# Every key the extractor can put in `entities`, in Persian. A field missing
# from this map printed its raw English key on screen — «case_type» beside
# «موضوع» — which is the one thing this UI is not allowed to do.
_FIELD_FA = {
    "title": "عنوان", "summary": "خلاصه", "kind": "نوع", "case_number": "شمارهٔ پرونده",
    "court": "مرجع رسیدگی", "branch": "شعبه", "date": "تاریخ", "year": "سال",
    "topic": "موضوع", "status": "وضعیت", "doc_kind": "نوع سند",
    # added with the insurance edition (v2)
    "case_type": "نوع پرونده", "insurance_line": "رشتهٔ بیمه‌ای",
    "claim_amount": "مبلغ خواسته", "outcome": "نتیجه", "filed_date": "تاریخ ثبت",
    "people": "اشخاص", "orgs": "سازمان‌ها",
}


def _field_value(key: str, value) -> str:
    """An entity value as it should appear on screen.

    Most values come out of the extractor already in Persian; `status` is the
    one field whose vocabulary is a fixed English enum in the schema
    (`open|closed|appeal`), so it is translated rather than printed raw.
    """
    from app.rag.casebase import STATUS_FA

    text = str(value)
    if key == "status":
        return STATUS_FA.get(text, text)
    return text


def _label_party(party) -> str:
    """A party as a line of text, whatever shape the extractor returned.

    The role arrives as the schema's transliterated key (`khahan`), which is
    what `parties` stores — so it is translated here, through the same map the
    case views use, rather than printed raw.
    """
    from app.rag.casebase import ROLE_FA

    if isinstance(party, dict):
        name = party.get("name") or party.get("party") or ""
        role = str(party.get("role") or "").strip()
        role = ROLE_FA.get(role, role)
        return f"{role}: {name}".strip(": ") if name else ""
    return str(party or "").strip()


def _label_event(event) -> str:
    """An event as a line of text. Extraction is model output, so an `events`
    list holds dicts most of the time and bare strings the rest of the time —
    calling .get() on those is what crashed the draft view."""
    if isinstance(event, dict):
        when = event.get("date") or ""
        what = event.get("what") or event.get("type") or event.get("detail") or ""
        return f"{when} — {what}".strip(" —") if (when or what) else ""
    return str(event or "").strip()


_STEP_FA = {
    "classify": "تشخیص نوع", "extract": "استخراج ساختاریافته", "references": "مستندات قانونی",
    "timeline": "خط زمان", "similar": "پرونده‌های مشابه", "labels": "برچسب‌ها", "commit": "ثبت در آرشیو",
}
_STEP_ORDER = ["classify", "extract", "references", "timeline", "similar", "labels", "commit"]
_GATE_ACTION = {
    "extract": "تأیید فیلدها و ادامه", "references": "تأیید مستندات و ادامه",
    "timeline": "تأیید خط زمان و ادامه",
    "similar": "تأیید موارد مشابه و ادامه", "labels": "تأیید برچسب‌ها و ثبت نهایی",
}
_WF_ICON = {"done": "✓", "failed": "✕", "running": "…", "awaiting_input": "⏳"}


def _draft_ticket(draft: dict) -> None:
    """The extracted record drawn as the ledger ticket it becomes — carried over
    from the old single-step draft view."""
    entities = draft.get("entities") or {}
    parties = draft.get("parties") or []
    events = draft.get("events") or []
    number = entities.get("case_number") or draft.get("case_number")
    missing = (
        [_FIELD_FA.get(k, k) for k in ("title", "summary") if not draft.get(k)]
        + ([] if number else ["شمارهٔ پرونده"]) + ([] if parties else ["طرفین"])
    )
    st.markdown(
        "<div class='card'>"
        f"<h4>{esc(draft.get('title') or 'بدون عنوان')}</h4>"
        f"<div style='margin:6px 0'>{case_id(number)}</div>"
        f"<div class='meta'>{esc(draft.get('summary') or '—')}</div>"
        + kv([(_FIELD_FA.get(k, k), _field_value(k, v)) for k, v in entities.items()
              if v and not isinstance(v, (list, dict))])
        + ("<div style='margin-top:8px'><b style='font-size:12px'>طرفین</b>"
           + chips([line for line in map(_label_party, parties) if line]) + "</div>"
           if parties else "")
        + ("<div style='margin-top:8px'><b style='font-size:12px'>رویدادها</b>"
           + chips([line for line in map(_label_event, events) if line]) + "</div>"
           if events else "")
        + ("<div style='margin-top:10px'>"
           + "".join(stamp(f"{m} استخراج نشده", "review") for m in missing) + "</div>"
           if missing else "<div style='margin-top:10px'>" + stamp("کامل", "teal") + "</div>")
        + "</div>",
        unsafe_allow_html=True,
    )


def _rail(view: dict) -> None:
    """The seven steps as one compact horizontal rail.

    The vertical stepper this replaces was taller than the record it described,
    which pushed the live question off the screen on a laptop. Here the run's
    shape is one line: a numbered dot per step, filled as it completes.
    """
    by_id = {s["step_id"]: s for s in view["steps"]}
    cells = ""
    for seq, sid in enumerate(_STEP_ORDER, start=1):
        step = by_id.get(sid, {"status": "pending"})
        status = step["status"]
        icon = _WF_ICON.get(status, fa_num(seq))
        cells += (
            f"<div class='rail-cell {status}'><div class='rail-dot'>{icon}</div>"
            f"<div class='rail-lbl'>{esc(_STEP_FA[sid])}</div></div>"
        )
    st.markdown(f"<div class='rail'>{cells}</div>", unsafe_allow_html=True)


def _draft_of(view: dict) -> dict:
    """The record as the run last saw it — for a run whose conversation is over
    (committed, abandoned, reloaded) and so has no live working copy."""
    for step in reversed(view.get("steps") or []):
        payload = step.get("payload") or {}
        if isinstance(payload.get("draft"), dict):
            return payload["draft"]
        if step["step_id"] == "extract" and payload.get("title") is not None:
            return payload
    return {}


def _render_pipeline(cfg: dict, message: dict, index: int) -> None:
    """The run's own turn: the rail, and the record as it stands.

    Deliberately *not* the gate — the questions are separate turns further down
    the transcript. This message is the header they belong to, so it stays
    short and never grows a form.
    """
    view = _wf_load(message["run_id"])
    if not view:
        st.error("اجرای خط لوله یافت نشد.")
        return

    _rail(view)

    live = askflow.active(message["run_id"])
    draft = askflow.record() if live else _draft_of(view)
    if draft:
        _draft_ticket(draft)

    if view["status"] == "committed":
        return
    if view["status"] == "abandoned":
        st.caption("این پیش‌نویس رها شد.")
        return

    failed = next((s for s in view["steps"] if s["status"] == "failed"), None)
    if failed:
        return  # its own turn says so, with the retry

    awaiting = next((s for s in view["steps"] if s["status"] == "awaiting_input"), None)
    if awaiting and not live:
        # The conversation was lost (a reload, a new session) but the run is
        # still parked at its gate — offer to pick the questions back up.
        st.caption(
            f"این اجرا در گام «{_STEP_FA.get(awaiting['step_id'], awaiting['step_id'])}» "
            "منتظر شماست."
        )
        if st.button("ادامهٔ گفتگو", key=f"wf_resume_ask_{index}", type="primary"):
            if askflow.begin(view, mode=st.session_state.get("wf_mode", "review")):
                _ask_next(view["id"])
            st.rerun()
        return

    running = next((s for s in view["steps"] if s["status"] == "running"), None)
    if running and not live:
        st.caption(f"گام «{_STEP_FA.get(running['step_id'], running['step_id'])}» ناتمام ماند.")
        if st.button("ادامه", key=f"wf_resume_{index}", type="primary"):
            with st.spinner("در حال ادامهٔ خط لوله…"):
                view = _wf_advance(cfg, message["run_id"])
            _after_advance(cfg, view)
            st.rerun()


def _render_ask(cfg: dict, message: dict, index: int) -> None:
    """One question. Its quick replies are live only while it is the open one —
    an answered question stays in the transcript as plain text, the way the rest
    of the conversation does."""
    step, total = message.get("step", 0), message.get("total", 0)
    counter = (f"<span class='ask-count'>پرسش {fa_num(step)} از {fa_num(total)}</span>"
               if total else "")
    st.markdown(
        f"<div class='ask'>{counter}<div class='ask-q'>{esc(message['prompt'])}</div>"
        f"{message.get('card') or ''}"
        + (f"<div class='ask-note'>{esc(message['note'])}</div>" if message.get("note") else "")
        + "</div>",
        unsafe_allow_html=True,
    )

    if message.get("done") or not askflow.active(message.get("run_id")):
        return
    if (askflow.current() or {}).get("id") != message.get("qid"):
        return

    quick = message.get("chips") or []
    if quick:
        for column, label in zip(st.columns(len(quick) + 1), quick):
            if column.button(label, key=f"ask_{index}_{label}", use_container_width=True):
                _say("user", text=label)
                st.rerun()
    st.caption("یا پاسخ را در کادر پایین بنویسید.")


def _render_filed(message: dict, index: int) -> None:
    entry_id = message.get("entry_id") or ""
    st.markdown(
        "<div class='ask'>" + stamp("مدخل در آرشیو ثبت شد", "teal")
        + (f"<div class='ask-note'>شناسهٔ مدخل: {esc(entry_id)}</div>" if entry_id else "")
        + "</div>",
        unsafe_allow_html=True,
    )
    if entry_id and st.button("باز کردن در «ویرایش مدخل‌ها»", key=f"filed_{index}"):
        st.session_state["editor_entry"] = entry_id
        st.session_state["view"] = "editor"
        st.rerun()


def _render_wf_failed(cfg: dict, message: dict, index: int) -> None:
    label = _STEP_FA.get(message.get("step", ""), message.get("step", ""))
    st.error(f"گام «{label}» ناموفق بود — {message.get('error') or ''}")
    cols = st.columns([3, 1])
    if cols[0].button("تلاش دوباره", key=f"wf_retry_{index}", type="primary",
                      use_container_width=True):
        with st.spinner("در حال اجرای دوبارهٔ گام…"):
            view = _wf_advance(cfg, message["run_id"])
        _after_advance(cfg, view)
        st.rerun()
    if cols[1].button("رهاکردن", key=f"wf_stop_fail_{index}", use_container_width=True):
        _wf_abandon(message["run_id"])
        askflow.clear()
        st.rerun()


def _render(cfg: dict, message: dict, index: int) -> None:
    if message["role"] == "user":
        with st.chat_message("user", avatar="🧑"):
            # Newlines become <br>: st.markdown parses the string as Markdown,
            # so a pasted document's blank lines turned the rest of the text
            # into <p> blocks that took Streamlit's paragraph colour — ink on
            # the ink-coloured bubble — and single line breaks collapsed.
            st.markdown(
                f"<div class='bubble-user'>{esc(message['text']).replace(chr(10), '<br>')}</div>",
                unsafe_allow_html=True,
            )
        # A failed turn keeps its text and shows why, with one-click retry —
        # rather than vanishing or being re-attempted on every rerun.
        if message.get("error"):
            with st.chat_message("assistant", avatar="⚖️"):
                st.error(f"پاسخ ناموفق — {message['error']}")
                if st.button("تلاش دوباره", key=f"retry_{index}"):
                    message.pop("error", None)
                    message.pop("answered", None)
                    st.rerun()
        return

    with st.chat_message("assistant", avatar="⚖️"):
        # The archive conversation's own turns: a question, its acknowledgement,
        # the filing, a failed step. Each is its own turn in the transcript.
        kind = message.get("kind")
        if kind == "ask":
            _render_ask(cfg, message, index)
            return
        if kind == "ack":
            st.markdown(
                f"<div class='ack'>{esc(message.get('text', ''))}</div>",
                unsafe_allow_html=True,
            )
            return
        if kind == "filed":
            _render_filed(message, index)
            return
        if kind == "wf_failed":
            _render_wf_failed(cfg, message, index)
            return

        intent = message.get("intent")
        if intent:
            st.markdown(
                f"<span class='intent-badge {intent}'>{esc(_INTENT_FA.get(intent, intent))}</span>",
                unsafe_allow_html=True,
            )
        if intent == "archive":
            _render_pipeline(cfg, message, index)
            return

        if intent == "unclear":
            st.markdown(
                f"<div class='answer'>{esc(message.get('text',''))}</div>",
                unsafe_allow_html=True,
            )
            # One click resends the original message with the intent pinned.
            original = message.get("pending_text", "")
            if original:
                cols = st.columns(5)
                for col, choice, label in zip(
                    cols, ("query", "law", "cases", "archive", "analytics"),
                    ("پرسش از اسناد", "قوانین", "پرونده‌ها", "ثبت مطلب", "آمار"),
                ):
                    if col.button(label, key=f"clarify_{index}_{choice}",
                                  use_container_width=True):
                        _say("user", text=original, forced_intent=choice)
                        st.rerun()
            return

        body = (message.get("text") or "").strip()
        # A stored message with reasoning but no answer must not render as an
        # empty bubble — that is what made replies look like they vanished once
        # the rerun replaced the live stream with the saved transcript.
        components.reasoning_panel(message.get("reasoning"), expanded=not body)
        if body:
            st.markdown(f"<div class='answer'>{esc(body)}</div>", unsafe_allow_html=True)
        else:
            st.warning(
                "مدل فقط استدلال کرد و پاسخی ننوشت. «سقف توکن خروجی» را بالا "
                "ببرید یا «میزان استدلال» را کم کنید."
            )

        if message.get("contexts"):
            with st.expander(f"مستندات ({fa_num(len(message['contexts']))} قطعه)"):
                selected = components.citations(
                    message["contexts"], document_action=True,
                    key_prefix=f"history_{index}",
                )
            if selected:
                st.session_state["source_preview"] = selected["document_id"]
                st.rerun()
        if message.get("law_refs"):
            with st.expander(f"مواد استنادشده ({fa_num(len(message['law_refs']))})"):
                for i, r in enumerate(message["law_refs"], 1):
                    st.markdown(
                        f"<div class='kv'><span class='k'>[{fa_num(i)}] {esc(r.get('cite',''))}</span>"
                        f"<span>{esc(r.get('title') or '')}</span></div>"
                        f"<div class='meta' style='white-space:pre-wrap;line-height:1.9'>{esc(r.get('text',''))}</div>",
                        unsafe_allow_html=True,
                    )
                if st.button("باز کردن در «قوانین و مستندات»", key=f"open_laws_{index}"):
                    st.session_state["laws_q"] = message.get("question", "")
                    st.session_state["view"] = "laws"
                    st.rerun()
        if message.get("case_hits"):
            with st.expander(f"پرونده‌های استنادشده ({fa_num(len(message['case_hits']))})"):
                components.rowlist_start()
                for i, c in enumerate(message["case_hits"], 1):
                    if components.row(
                        f"[{fa_num(i)}] {c.get('title') or c.get('case_number')}",
                        f"شماره {fa_num(c.get('case_number',''))} · {c.get('case_type') or '—'} · {c.get('status_fa') or ''}",
                        (c.get("outcome") or "")[:120] or None,
                        key=f"case_hit_{index}_{i}",
                    ):
                        st.session_state["open_case"] = c.get("case_number")
                        st.session_state["view"] = "cases"
                        st.rerun()
        if message.get("stats"):
            with st.expander("دادهٔ خام"):
                st.json(message["stats"])
        if message.get("model"):
            components.usage_caption(model=message["model"])


# --------------------------------------------------------------------------- #
def _submit(cfg: dict, text: str) -> None:
    """Queue the message and rerun — the reply is generated by `_answer_pending`,
    from the history loop, on the run that follows.

    Answering immediately, here, would run *after* the composer's own widgets
    have already been drawn (`_submit` is only ever reached from inside
    `_composer`), which puts the reply below the composer in document order.
    That is invisible with a normal in-flow composer, but the composer is
    `position: sticky` so it stays pinned near the bottom of the viewport —
    and a reply placed after it in the DOM would stream in underneath that
    pinned bar, out of view, until the final rerun put things back in order.
    Queuing avoids the whole problem: the next run's history loop renders the
    user's turn, `_answer_pending` answers it right there, and only then does
    the composer draw again — so the reply is always above it.
    """
    _say("user", text=text)
    st.rerun()


def _answer_pending(cfg: dict) -> None:
    """Generate a reply for the trailing message, if it's an unanswered user turn."""
    history = _history()
    if not history or history[-1]["role"] != "user":
        return
    turn = history[-1]
    # A turn that already errored must not be retried on every rerun — that is
    # what turned one 500 into a wall of them and a dead-looking app.
    if turn.get("error") or turn.get("answered"):
        return
    text = turn["text"]

    # An archive conversation in progress owns the next turn: the text is an
    # answer to the question on screen, not a new message to route.
    if askflow.active():
        try:
            _archive_turn(cfg, text)
        except Exception as error:  # noqa: BLE001
            turn["error"] = f"{type(error).__name__}: {error}"
        else:
            turn["answered"] = True
        st.rerun()
        return

    # Pre-flight: a doomed call (model unreachable) should fail fast and clearly,
    # not fire off, 500, and leave the turn to be retried forever.
    if not cfg["entry"].get("available", True):
        turn["error"] = (
            f"مدل «{cfg['entry']['label']}» در دسترس نیست: "
            f"{cfg['entry'].get('reason') or 'اتصال برقرار نشد'}. "
            "مدل دیگری از نوار سمت چپ انتخاب کنید."
        )
        st.rerun()
        return

    # A per-message intent (from a clarification quick-reply) wins over the
    # sidebar selector, which applies to whatever the user types next.
    forced = turn.get("forced_intent") or st.session_state.get("agent_intent") or "auto"
    with st.chat_message("assistant", avatar="⚖️"):
        try:
            with st.status("در حال تشخیص نوع پیام…", expanded=False) as status:
                decision = aio.run(route(
                    _active_llm(cfg), text,
                    forced=None if forced == "auto" else forced,
                ))
                status.update(
                    label=f"نوع پیام: {_INTENT_FA.get(decision.intent, decision.intent)}"
                          + f" · مدل: {cfg['entry']['label']}",
                    state="complete",
                )
            intent = decision.intent
            st.markdown(
                f"<span class='intent-badge {intent}'>{esc(_INTENT_FA.get(intent, intent))}</span>",
                unsafe_allow_html=True,
            )
            # Same five-way vocabulary the FastAPI /assistant path uses — the
            # decision comes from one `route()`, only the execution differs
            # (streamed here, a dict there).
            if intent == "unclear":
                _clarify(decision, text)
            elif intent == "chat":
                _chat_reply(cfg, text)
            elif intent == "archive":
                _draft_for_archive(
                    cfg, text, forced="archive" if forced == "archive" else None,
                )
            elif intent == "analytics":
                _archive_stats(cfg, text)
            elif intent == "law":
                _answer_from_laws(cfg, text)
            elif intent == "cases":
                _answer_from_cases(cfg, text)
            else:
                _answer_from_archive(cfg, text)
        except Exception as error:  # noqa: BLE001
            # Keep the user's text — store the failure on the turn so it renders
            # as a ret ryable error and is not attempted again automatically.
            turn["error"] = f"{type(error).__name__}: {error}"
        else:
            turn["answered"] = True
    st.rerun()


def _answer_from_laws(cfg: dict, text: str) -> None:
    """The «legal context» route: articles from the law base, answer cites [n]."""
    from app.rag.lawbase import answer_law_question

    async def _go():
        async with session() as s:
            return await answer_law_question(s, _active_llm(cfg), text, max_tokens=cfg.get("max_tokens") or 1400)

    with st.spinner("در حال جستجو در پایگاه قوانین…"):
        result = aio.run(_go())
    st.markdown(f"<div class='answer'>{esc(result.get('answer',''))}</div>", unsafe_allow_html=True)
    components.steps_panel(result.get("steps", []))
    _say("assistant", intent="law", text=result.get("answer", ""), law_refs=result.get("refs", []),
         question=text, model=result.get("model"))


def _answer_from_cases(cfg: dict, text: str) -> None:
    """The «case archive» route: structured case records, answer cites [n]."""
    from app.rag.casebase import answer_case_question

    async def _go():
        async with session() as s:
            return await answer_case_question(s, _active_llm(cfg), text, max_tokens=cfg.get("max_tokens") or 1400)

    with st.spinner("در حال جستجو در بایگانی پرونده‌ها…"):
        result = aio.run(_go())
    st.markdown(f"<div class='answer'>{esc(result.get('answer',''))}</div>", unsafe_allow_html=True)
    components.steps_panel(result.get("steps", []))
    hits = [
        {k: c.get(k) for k in ("id", "case_number", "title", "case_type", "insurance_line", "status_fa", "outcome")}
        for c in result.get("cases", [])
    ]
    _say("assistant", intent="cases", text=result.get("answer", ""), case_hits=hits, model=result.get("model"))


def _chat_reply(cfg: dict, text: str) -> None:
    """A plain conversational turn — no retrieval, nothing written."""
    box = st.empty()
    parts: list[str] = []
    stream = _active_llm(cfg).stream(
        text,
        system=(
            "You are the assistant of a Persian legal archive. Reply briefly and "
            "helpfully in the user's language. You have not consulted the archive "
            "for this message — if they want that, invite them to ask about a case."
        ),
        max_tokens=600, **cfg["knobs"],
    )
    for event in aio.iterate(stream):
        if event["type"] == "answer":
            parts.append(event["delta"])
            box.markdown(f"<div class='answer'>{esc(''.join(parts))}</div>", unsafe_allow_html=True)
    _say("assistant", intent="chat", text="".join(parts))


def _clarify(decision, text: str) -> None:
    """The router wasn't sure. Ask, and offer the likely intents as one click."""
    question = decision.clarification or "منظورتان چیست؟"
    st.markdown(f"<div class='answer'>{esc(question)}</div>", unsafe_allow_html=True)
    _say("assistant", intent="unclear", text=question, pending_text=text)


_WF_MODE_FA = {
    "review": "تأیید یک‌باره", "steps": "گام‌به‌گام", "auto": "خودکار",
}


def _controls(cfg: dict) -> None:
    """Per-message choices: what kind of message this is, and — for a new
    entry — how much the pipeline stops for you. Model and STT choices are
    settings and live in the left panel."""
    if st.session_state.pop("compose_intent", None) == "archive":
        st.session_state["agent_intent"] = "archive"
    left, right = st.columns(2)
    with left:
        st.selectbox(
            "نوع پیام", ["auto", "query", "law", "cases", "archive", "analytics", "chat"],
            format_func=lambda k: "تشخیص خودکار" if k == "auto" else _INTENT_FA[k],
            key="agent_intent", label_visibility="collapsed",
            help="به‌صورت پیش‌فرض سامانه خودش تشخیص می‌دهد؛ می‌توانید دستی تعیین کنید.",
        )
    with right:
        st.selectbox(
            "حالت ثبت مدخل", ["review", "steps", "auto"],
            format_func=lambda k: _WF_MODE_FA[k],
            key="wf_mode", label_visibility="collapsed",
            help=(
                "«تأیید یک‌باره»: همه‌چیز اجرا می‌شود و فقط یک‌بار برای بازبینی "
                "می‌ایستد و تنها فیلدهای خالی را می‌پرسد. «گام‌به‌گام»: در هر مرحله "
                "می‌ایستد. «خودکار»: بدون توقف ثبت می‌کند."
            ),
        )


def _active_llm(cfg: dict):
    """The model from the left panel."""
    return cfg["llm"]


def _composer(cfg: dict) -> None:
    """One native Streamlit control for typed and recorded messages."""
    with st.container(key="composer_wrap"):
        submission = st.chat_input(
            "پیام خود را بنویسید یا بگویید…",
            key="composer",
            accept_audio=stt.enabled(),
            audio_sample_rate=16000,
        )

    if not submission:
        return
    if isinstance(submission, str):
        typed, audio = submission, None
    else:
        typed, audio = submission.text, submission.audio

    # A recording is just another way of typing: transcribe it, then send it.
    if audio is not None:
        fingerprint = hash(audio.getvalue())
        if st.session_state.get("_mic_done") != fingerprint:
            st.session_state["_mic_done"] = fingerprint
            try:
                with st.spinner("در حال رونویسی…"):
                    result = aio.run(stt.transcribe(
                        audio.getvalue(), "audio.wav",
                        choice=st.session_state.get("agent_stt"),
                    ))
            except Exception as error:  # noqa: BLE001
                components.error_box(error)
                return
            spoken = (result or {}).get("text", "").strip()
            if spoken:
                _submit(cfg, spoken)
            else:
                st.warning("چیزی شنیده نشد.")

    if typed:
        _submit(cfg, typed)


def render(cfg: dict, state: dict) -> None:
    """Chips when the conversation is empty, the transcript once it isn't, and
    the composer. Nothing else — this screen is a chat, and the model and
    retrieval controls already live in the left panel."""
    history = _history()

    if not history:
        st.caption("بنویسید یا بگویید — سامانه خودش تشخیص می‌دهد.")
        for column, example in zip(st.columns(len(_EXAMPLES)), _EXAMPLES):
            if column.button(example, key=f"ex_{example[:10]}", use_container_width=True):
                _submit(cfg, example)
    else:
        head = st.columns([5, 1])
        head[1].button(
            "گفتگوی جدید", key="chat_clear", use_container_width=True,
            on_click=lambda: st.session_state.update(chat=[]),
        )

    for index, message in enumerate(history):
        _render(cfg, message, index)

    _source_preview(cfg)
    _answer_pending(cfg)

    _controls(cfg)
    _composer(cfg)

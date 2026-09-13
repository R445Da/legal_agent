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

from app.llm.meter import usage_of
from app.rag import conversation, conversations, entryedit
from app.rag import provenance as prov
from app.rag import runs, transcribe as stt, voice, workflow
from app.rag.orchestrator import _INTENT_FA, attach_provenance, corpus_stats, route, similar_stage
from app.rag.ingest import get_document
from app.rag.pipeline import SYSTEM_PROMPT, build_prompt, format_source, snippet
from app.rag.catalog import search_entries
from app.rag.retriever import retrieve_scored
from app.rag.textnorm import normalize_fa
from app.ui import aio, askflow, components, data, speak
from app.ui.views import graphmap
from app.ui.resources import session
from app.ui.theme import card, case_id, chips, esc, fa_ms, fa_num, kv, stamp

def _conversation_id() -> str:
    """The thread this tab is on, created on first use.

    The chat used to be a list in `st.session_state`, which made it a property
    of one browser tab: a reload lost it and nothing else could see it. The
    list is still here as a per-rerun cache, but the rows are the truth.
    """
    cid = st.session_state.get("conversation_id")
    if cid:
        return cid

    async def _start():
        async with session() as s:
            return await conversations.start(s, source="ui")

    convo = aio.run(_start())
    st.session_state["conversation_id"] = convo["id"]
    st.session_state["chat"] = []
    return convo["id"]


def _load_conversation(conversation_id: str) -> None:
    """Open an existing thread — its turns and what it was working on."""
    async def _go():
        async with session() as s:
            return await conversations.get(s, conversation_id)

    convo = aio.run(_go())
    if not convo:
        return
    st.session_state["conversation_id"] = convo["id"]
    st.session_state["chat"] = convo["messages"]
    st.session_state["chat_focus"] = convo.get("focus") or {}


def _history() -> list[dict]:
    return st.session_state.setdefault("chat", [])


def _say(role: str, **fields) -> dict:
    """Append a turn to the transcript and to the thread it belongs to."""
    message = {"role": role, **fields}
    _history().append(message)

    cid = _conversation_id()
    text = str(fields.get("text") or "")
    extra = {k: v for k, v in fields.items()
             if k not in ("text", "intent", "model") and _jsonable(v)}

    async def _persist():
        async with session() as s:
            await conversations.add_message(
                s, cid, role=role, text=text,
                intent=fields.get("intent"), model=fields.get("model"), **extra,
            )

    try:
        aio.run(_persist())
    except Exception:  # noqa: BLE001 — a chat must not die because a write did
        pass
    return message


def _jsonable(value) -> bool:
    """`extra` is a JSONB column; a provenance block with a datetime in it
    would abort the whole turn's write."""
    import json

    try:
        json.dumps(value, ensure_ascii=False)
        return True
    except (TypeError, ValueError):
        return False


def _focus(kind: str, record_id, label: str = "") -> None:
    """Record what the conversation is now working on, so «نشانش بده» or
    «یک رویداد به تایم‌لاینش اضافه کن» resolves without naming it again."""
    cid = st.session_state.get("conversation_id")
    if not cid:
        return
    st.session_state["chat_focus"] = {"kind": kind, "id": str(record_id), "label": label}

    async def _go():
        async with session() as s:
            await conversations.set_focus(s, cid, kind=kind, id=record_id, label=label)

    try:
        aio.run(_go())
    except Exception:  # noqa: BLE001
        pass


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

    res = {
        "answer": text_out, "contexts": contexts, "model": final.model if final else cfg["model_id"],
        "latency_ms": final.latency_ms if final else None, "usage": usage_of([final]) if final else {},
        "steps": [],
    }
    extra = _similar_after(cfg, "query", text, res)
    _show_similar(extra, offset=len(contexts), key_prefix="live_query")
    block = prov.build_provenance(
        intent="query", provider=getattr(_active_llm(cfg), "name", None),
        model=res["model"],
        evidence=prov.evidence_from_contexts(contexts) + list(res.get("similar_evidence") or []),
        usage=res["usage"], answer=text_out + ("\n\n" + res["advice"] if res.get("advice") else ""),
        latency_ms=res["latency_ms"],
    )
    _persist_answer("query", text, text_out, block, model=final.model if final else None)
    components.provenance_panel(block, key_prefix="live_query")

    _say(
        "assistant", intent="query", text=text_out,
        reasoning="".join(thoughts) or None,
        contexts=contexts, trace=trace,
        model=res["model"],
        latency_ms=res["latency_ms"],
        provenance=block, **extra,
    )


def _similar_after(cfg: dict, intent: str, question: str, res: dict) -> dict:
    """Run the similar-case stage on a finished answer (in place) and return
    the keys worth keeping on the chat message."""
    async def _go():
        async with session() as s:
            await similar_stage(s, _active_llm(cfg), intent, question, res)

    try:
        with st.spinner("در جستجوی پرونده‌های مشابه در گراف…"):
            aio.run(_go())
    except Exception as error:  # noqa: BLE001 — the answer stands without it
        res.setdefault("steps", []).append({"name": "پرونده‌های مشابه", "detail": f"ناموفق: {error}"[:160]})
    return {k: res[k] for k in ("similar_cases", "lessons", "advice") if res.get(k)}


def _show_similar(message: dict, *, offset: int, key_prefix: str) -> None:
    """Draw the similar-case panel; a click opens the case in «پرونده‌ها»."""
    clicked = components.similar_cases_panel(
        message.get("similar_cases"), message.get("lessons"), message.get("advice"),
        key_prefix=key_prefix, offset=offset,
    )
    if clicked:
        st.session_state["open_case"] = clicked
        st.session_state["view"] = "cases"
        st.rerun()


def _persist_answer(intent: str, question: str, answer: str, block: dict, *, model: str | None) -> None:
    """Record the answer + provenance; a storage hiccup must not lose the reply."""
    async def _go():
        async with session() as s:
            return await prov.persist_answer(
                s, intent=intent, question=question, answer=answer, provenance=block,
                model=model, source="ui",
            )
    try:
        aio.run(_go())
    except Exception:  # noqa: BLE001 — best-effort bookkeeping
        pass


def _answer_with_agent(cfg: dict, text: str) -> None:
    """The «پژوهش عاملی» route: the model researches with the read-only tools,
    each call shown as it happens, then answers from the numbered evidence."""
    from app.rag.agent import AGENT_SYSTEM, steps_from
    from app.rag.tools import EvidenceLedger, iter_with_tools

    llm = _active_llm(cfg)
    ledger = EvidenceLedger()
    holder: dict = {}

    async def _events():
        async with session() as s:
            async for event in iter_with_tools(
                llm, s, f"Question: {text}", system=AGENT_SYSTEM, max_rounds=4,
                max_tokens=cfg.get("max_tokens") or 1400, ledger=ledger,
            ):
                yield event

    started = dt.datetime.now()
    with st.status("عامل در حال پژوهش در آرشیو…", expanded=True) as status:
        for event in aio.iterate(_events()):
            kind = event["type"]
            if kind == "round":
                st.caption(f"دور {fa_num(event['round'])}")
            elif kind == "tool_call":
                args = "، ".join(f"{k}={v}" for k, v in (event.get("args") or {}).items() if v not in (None, ""))
                st.markdown(
                    f"<div class='kv'><span class='k mono'>{esc(event['tool'])}</span>"
                    f"<span>{esc(args)}</span></div>", unsafe_allow_html=True,
                )
            elif kind == "tool_result":
                mark = "⚠️" if event.get("error") else "✓"
                st.caption(f"{mark} {event['summary']} · {fa_ms(event.get('ms'))}")
            elif kind == "done":
                holder["result"] = event["result"]
        result = holder.get("result")
        if result is None:
            status.update(label="عامل پاسخی نداد", state="error")
            return
        status.update(
            label=f"پژوهش تمام شد — {fa_num(len(result.tool_log))} فراخوانی، {fa_num(len(result.evidence))} شاهد",
            state="complete",
        )

    total_ms = (dt.datetime.now() - started).total_seconds() * 1000
    block = prov.build_provenance(
        intent="agent", provider=getattr(llm, "name", None), model=result.model,
        evidence=result.evidence, tool_trail=result.tool_log, usage=result.usage,
        answer=result.text, latency_ms=total_ms,
        extra={"loop": result.mode, "rounds": result.rounds},
    )
    _persist_answer("agent", text, result.text, block, model=result.model)

    # Light up section ۲۰ with whatever the tools actually reached, so the
    # graph shows the run instead of only the transcript.
    graphmap.highlight_for([
        str(item.get("case_number") or item.get("title") or item.get("id") or "")
        for item in (result.evidence or [])
    ])

    components.reasoning_panel(result.reasoning)
    if result.text.strip():
        st.markdown(f"<div class='answer'>{esc(result.text)}</div>", unsafe_allow_html=True)
    else:
        st.warning("عامل ابزارها را فراخواند اما پاسخی ننوشت. سقف توکن خروجی را بالا ببرید.")
    components.provenance_panel(block, key_prefix="live_agent")
    components.steps_panel(steps_from(result, round(total_ms)))
    # `propose_edit` / `propose_append` wrote nothing — the proposal rides out
    # on the turn and the gate below the answer is what applies it.
    pending_edit = next(
        (row["proposal"] for row in reversed(result.tool_log) if row.get("proposal")), None)

    _say(
        "assistant", intent="agent", text=result.text, reasoning=result.reasoning,
        model=result.model, latency_ms=total_ms, provenance=block,
        pending_edit=pending_edit,
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
    mode = st.session_state.get("wf_mode", "conversation")
    spinner = {
        "review": "در حال استخراج مدخل — یک بار برای بازبینی می‌ایستد…",
        "steps": "در حال آغاز خط لوله — گام‌به‌گام…",
        "auto": "در حال استخراج و ثبت خودکار مدخل…",
        "conversation": "در حال استخراج مدخل — آنچه کم باشد را می‌پرسم…",
    }.get(mode, "در حال آغاز خط لوله…")
    with st.status(spinner, expanded=False) as status:
        view = _wf_start(cfg, text, source, mode=mode, forced=forced)
        if view["status"] == "committed":
            status.update(label="مدخل ثبت شد", state="complete")
        else:
            awaiting = next((s for s in view["steps"] if s["status"] == "awaiting_input"), None)
            status.update(
                label="آمادهٔ بازبینی" if awaiting else "خط لوله آغاز شد",
                state="complete",
            )
    question = conversation.last_question(view) if conversation.is_waiting(view) else None
    if question:
        # The next composer message answers this run, not the router.
        st.session_state["pending_run"] = view["id"]
    _say("assistant", intent="archive", run_id=view["id"], text=question)


def _pending_conversation() -> str | None:
    """The conversation-mode run waiting for the user's next message, if any.

    The id is cached in session state but re-derived from the transcript on
    every call, so a rerun or a fresh tab that still holds the chat history
    resumes the same run; the database decides whether it is really waiting.
    """
    run_id = st.session_state.get("pending_run")
    if not run_id:
        for message in reversed(_history()):
            if message.get("role") == "assistant" and message.get("intent") == "archive" and message.get("run_id"):
                run_id = message["run_id"]
                break
    if not run_id:
        return None
    if conversation.is_waiting(_wf_load(run_id)):
        st.session_state["pending_run"] = run_id
        return run_id
    st.session_state.pop("pending_run", None)
    return None


def _conversation_turn(cfg: dict, run_id: str, text: str) -> None:
    """One reply of a «گفتگویی» run: merge it, then either the next question
    or the committed record shows up as the assistant's message."""
    async def _go():
        async with session() as s:
            return await conversation.turn(s, run_id, cfg["llm"], text)

    with st.status("در حال به‌روزرسانی پیش‌نویس از پاسخ شما…", expanded=False) as status:
        view = aio.run(_go())
        label = {"committed": "مدخل ثبت شد", "awaiting_input": "پرسش بعدی",
                 "abandoned": "ثبت متوقف شد"}.get(view["status"], "ادامهٔ خط لوله")
        status.update(label=label, state="complete")
    if not conversation.is_waiting(view):
        st.session_state.pop("pending_run", None)
    # The engine records a one-line acknowledgement of what the answer did
    # («شمارهٔ کلاسه ثبت شد.»); it reads as punctuation between questions.
    turns = ((view.get("state") or {}).get("conversation") or {}).get("turns") or []
    ack = next((t.get("ack") for t in reversed(turns) if t.get("role") == "user"), "")
    if ack:
        _say("assistant", kind="ack", text=ack)
    _say("assistant", intent="archive", run_id=run_id,
         text=conversation.last_question(view) if conversation.is_waiting(view) else None)


def _latest_for_run(index: int, run_id: str | None) -> bool:
    """Only the newest message of a run draws the live pipeline; older ones
    keep their question text so the dialogue reads top to bottom."""
    if not run_id:
        return True
    return not any(
        m.get("run_id") == run_id and i > index for i, m in enumerate(_history())
    )


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
_FIELD_FA = {
    "title": "عنوان", "summary": "خلاصه", "kind": "نوع", "case_number": "شمارهٔ پرونده",
    "court": "مرجع رسیدگی", "branch": "شعبه", "date": "تاریخ", "year": "سال",
    "topic": "موضوع", "status": "وضعیت", "doc_kind": "نوع سند",
}


def _label_party(party) -> str:
    """A party as a line of text, whatever shape the extractor returned."""
    if isinstance(party, dict):
        name = party.get("name") or party.get("party") or ""
        role = party.get("role") or ""
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
        + kv([(_FIELD_FA.get(k, k), v) for k, v in entities.items()
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
    shape is one line: a numbered dot per step, filled as it completes. The
    dimming of what has not been reached is carried over from the first
    prototype's animated ingest pipeline.
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


def _render_pipeline(cfg: dict, message: dict, index: int) -> None:
    """The archive path: the six-step run, and whichever gate it is waiting on."""
    view = _wf_load(message["run_id"])
    if not view:
        st.error("اجرای خط لوله یافت نشد.")
        return

    _rail(view)

    if view["status"] == "committed":
        entry_id = view.get("entry_id") or ""
        st.markdown(stamp("مدخل در آرشیو ثبت شد", "teal"), unsafe_allow_html=True)
        st.caption(f"شناسهٔ مدخل: {esc(entry_id)}")
        if not message.get("_refreshed"):
            message["_refreshed"] = True
            data.refresh()
        return
    if view["status"] == "abandoned":
        st.caption("این خط لوله متوقف شد.")
        return

    failed = next((s for s in view["steps"] if s["status"] == "failed"), None)
    if failed:
        st.error(f"گام «{_STEP_FA.get(failed['step_id'], failed['step_id'])}» ناموفق بود — "
                 f"{failed.get('error') or ''}")
        cols = st.columns([3, 1])
        if cols[0].button("تلاش دوباره", key=f"wf_retry_{index}", type="primary",
                          use_container_width=True):
            with st.spinner("در حال اجرای دوبارهٔ گام…"):
                _wf_advance(cfg, message["run_id"])
            st.rerun()
        if cols[1].button("توقف", key=f"wf_stop_fail_{index}", use_container_width=True):
            _wf_abandon(message["run_id"])
            st.rerun()
        return

    awaiting = next((s for s in view["steps"] if s["status"] == "awaiting_input"), None)
    if awaiting:
        _render_gate(cfg, message["run_id"], awaiting, index)
        return

    # A step still marked "running" with nothing awaiting means the advance call
    # that started it was interrupted (tab closed, reload). Offer to resume it.
    running = next((s for s in view["steps"] if s["status"] == "running"), None)
    if running:
        st.caption(f"گام «{_STEP_FA.get(running['step_id'], running['step_id'])}» ناتمام ماند.")
        if st.button("ادامه", key=f"wf_resume_{index}", type="primary"):
            with st.spinner("در حال ادامهٔ خط لوله…"):
                _wf_advance(cfg, message["run_id"])
            st.rerun()


def _render_gate(cfg: dict, run_id: str, step: dict, index: int) -> None:
    sid = step["step_id"]
    payload = step.get("payload") or {}
    review = sid == "labels" and payload.get("mode") == "review"

    if sid == "labels" and payload.get("mode") == "conversation":
        st.markdown(
            "<span class='intent-badge archive'>در انتظار پاسخ شما در گفتگو</span>",
            unsafe_allow_html=True,
        )
        _gate_conversation(cfg, run_id, payload, index)
        return

    heading = "بازبینی نهایی و ثبت" if review else _STEP_FA.get(sid, sid)
    st.markdown(
        f"<span class='intent-badge archive'>در انتظار تأیید شما — {esc(heading)}</span>",
        unsafe_allow_html=True,
    )

    if review:
        patch = _gate_review(payload, index)
        action = "تأیید و ثبت در آرشیو"
    elif sid == "extract":
        patch = {"draft": _gate_extract(payload, index)}
        action = _GATE_ACTION["extract"]
    elif sid == "references":
        patch = {"references": _gate_references(payload.get("rows") or [], index)}
        action = _GATE_ACTION["references"]
    elif sid == "timeline":
        patch = {"timeline": _gate_timeline(payload.get("rows") or [], index)}
        action = _GATE_ACTION["timeline"]
    elif sid == "similar":
        patch = {"similar": _gate_similar(payload, index)}
        action = _GATE_ACTION["similar"]
    elif sid == "labels":
        patch = {"labels": _gate_labels(payload.get("labels") or [], index)}
        action = _GATE_ACTION["labels"]
    else:
        patch, action = {}, "تأیید و ادامه"

    go, stop = st.columns([3, 1])
    if go.button(action, key=f"wf_go_{index}_{sid}", type="primary",
                 use_container_width=True):
        with st.spinner("در حال ثبت…" if review else "در حال اجرای گام بعدی…"):
            _wf_advance(cfg, run_id, user_patch=patch)
        st.rerun()
    if stop.button("توقف", key=f"wf_stop_{index}_{sid}", use_container_width=True):
        _wf_abandon(run_id)
        st.rerun()


def _gate_conversation(cfg: dict, run_id: str, payload: dict, index: int) -> None:
    """The «گفتگویی» stop: the question the dialogue is on, its quick replies,
    and the record as it stands.

    One question, not the whole record — the queue lives in the run state
    (`app/rag/conversation.py`), so this only has to draw the current step of
    it. Tapping a chip sends that word as the user's turn, which is the same
    path as typing it, so the transcript reads the same either way.
    """
    question = payload.get("question")
    if not question:
        # No queue (an older run, or the dialogue is between questions): fall
        # back to the opening summary message.
        st.markdown(
            f"<div class='answer'>{esc(payload.get('message') or '').replace(chr(10), '<br>')}</div>",
            unsafe_allow_html=True,
        )
    else:
        conv = payload.get("conversation") or {}
        step, total = conversation.question_progress(conv)
        st.markdown(askflow.question_html(question, step=step, total=total),
                    unsafe_allow_html=True)

        quick = question.get("chips") or []
        if quick:
            for column, label in zip(st.columns(len(quick) + 1), quick):
                if column.button(label, key=f"ask_{index}_{run_id[:8]}_{label}",
                                 use_container_width=True):
                    _say("user", text=label)
                    st.rerun()
        st.caption("یا پاسخ را در کادر پایین بنویسید.")

    with st.expander("پیش‌نویس فعلی"):
        _draft_ticket(dict(payload.get("draft") or {}))
        unresolved = [r for r in (payload.get("references") or []) if not r.get("resolved")]
        if unresolved:
            st.caption(f"{fa_num(len(unresolved))} استناد هنوز به پایگاه قوانین متصل نشده است.")

    turns = (payload.get("conversation") or {}).get("turns") or []
    if len(turns) > 1:
        with st.expander(f"گفتگوی ثبت تا این‌جا ({fa_num(len(turns))} پیام)"):
            for t in turns:
                who = "کاربر" if t.get("role") == "user" else "دستیار"
                st.markdown(
                    f"<div class='kv'><span class='k'>{who}</span>"
                    f"<span style='white-space:pre-wrap'>{esc(t.get('text', ''))}</span></div>",
                    unsafe_allow_html=True,
                )

    if st.button("توقف", key=f"wf_stop_{index}_conversation", use_container_width=False):
        _wf_abandon(run_id)
        st.session_state.pop("pending_run", None)
        st.rerun()


def _gate_review(payload: dict, index: int) -> dict:
    """The single «تأیید یک‌باره» panel: the whole record at a glance, a short
    form for only the fields that came back empty, and the timeline / similar /
    labels tucked into an expander for anyone who wants to adjust them."""
    draft = dict(payload.get("draft") or {})
    draft["entities"] = {**(draft.get("entities") or {})}
    _draft_ticket(draft)

    missing = payload.get("missing") or []
    if missing:
        st.caption("این‌ها در متن پیدا نشدند — اگر می‌دانید پر کنید (اختیاری):")
        for path, fa in missing:
            val = st.text_input(fa, key=f"wf_miss_{index}_{path}")
            if val.strip():
                if path.startswith("entities."):
                    draft["entities"][path.split(".", 1)[1]] = val.strip()
                else:
                    draft[path] = val.strip()

    timeline = payload.get("timeline") or []
    similar = payload.get("similar") or []
    labels = payload.get("labels") or []
    references = payload.get("references") or []
    unresolved = [r for r in references if not r.get("resolved")]
    if unresolved:
        st.warning(
            f"{fa_num(len(unresolved))} استناد به پایگاه قوانین متصل نشد — در «ویرایش جزئیات» "
            "نام قانون/شمارهٔ ماده را اصلاح کنید یا تیک آن را بردارید."
        )
    with st.expander(
        f"ویرایش جزئیات — فیلدها، مستندات ({fa_num(len(references))})، خط زمان ({fa_num(len(timeline))})، "
        f"مشابه‌ها ({fa_num(len(similar))})، برچسب‌ها ({fa_num(len(labels))})"
    ):
        st.caption("فیلدهای مدخل")
        draft = _edit_fields(draft, index)
        st.caption("مستندات قانونی — ارجاع‌های استخراج‌شده و اتصال آن‌ها به پایگاه قوانین")
        references = _gate_references(references, index)
        st.caption("خط زمان")
        timeline = _gate_timeline(timeline, index)
        st.caption("پرونده‌های مشابه — تیک موارد نامرتبط را بردارید")
        similar = _gate_similar({"items": similar, "tool_log": payload.get("tool_log")}, index)
        st.caption("برچسب‌ها")
        labels = _gate_labels(labels, index)

    return {"draft": draft, "timeline": timeline, "similar": similar, "labels": labels,
            "references": references}


def _edit_fields(draft: dict, index: int) -> dict:
    """A table of every plain (string) field in the draft, editable. Nested
    `entities.*` are flattened with a prefix and re-nested on the way out."""
    rows = [
        {"فیلد": _FIELD_FA.get(k, k), "کلید": k, "مقدار": "" if v is None else str(v)}
        for k, v in draft.items() if isinstance(v, str) or v is None
    ] + [
        {"فیلد": _FIELD_FA.get(k, k), "کلید": f"entities.{k}", "مقدار": "" if v is None else str(v)}
        for k, v in (draft.get("entities") or {}).items() if isinstance(v, str) or v is None
    ]
    edited = st.data_editor(
        rows, use_container_width=True, hide_index=True, key=f"wf_draft_{index}",
        column_config={"کلید": None},
    )
    merged = {**draft, "entities": {**(draft.get("entities") or {})}}
    for row in edited:
        key, value = row["کلید"], row["مقدار"]
        if key.startswith("entities."):
            merged["entities"][key[len("entities."):]] = value
        elif not isinstance(merged.get(key), (list, dict)):
            merged[key] = value
    return merged


def _gate_extract(draft: dict, index: int) -> dict:
    _draft_ticket(draft)
    with st.expander("ویرایش فیلدها"):
        return _edit_fields(draft, index)


def _gate_timeline(rows: list[dict], index: int) -> list[dict]:
    edited = st.data_editor(
        rows or [{"date": "", "title": "", "detail": "", "source": ""}],
        use_container_width=True, hide_index=True, num_rows="dynamic",
        key=f"wf_tl_{index}",
        column_config={
            "date": st.column_config.TextColumn("تاریخ"),
            "title": st.column_config.TextColumn("رویداد", width="large"),
            "detail": st.column_config.TextColumn("توضیح"),
            "source": st.column_config.TextColumn("منبع"),
        },
    )
    return [r for r in edited if str(r.get("title") or "").strip()]


def _gate_similar(payload: dict, index: int) -> list[dict]:
    items = payload.get("items") or []
    tool_log = payload.get("tool_log") or []
    if tool_log:
        with st.expander(f"ردپای عامل — {fa_num(len(tool_log))} فراخوانی ابزار", expanded=False):
            for call in tool_log:
                st.caption(f"• {call.get('summary', '')}")
    if not items:
        st.caption("موردی یافت نشد — می‌توانید بدون پیوند ادامه دهید.")
        return []
    edited = st.data_editor(
        [{"نگه‌داری": bool(it.get("keep", True)), "عنوان": it.get("title", ""),
          "نتیجهٔ گذشته": it.get("outcome", ""), "علت پیوند": it.get("why", "")} for it in items],
        use_container_width=True, hide_index=True, key=f"wf_sim_{index}",
        column_config={
            "عنوان": st.column_config.TextColumn(disabled=True),
            "نتیجهٔ گذشته": st.column_config.TextColumn(disabled=True),
            "علت پیوند": st.column_config.TextColumn(disabled=True),
        },
    )
    return [{**it, "keep": bool(row["نگه‌داری"])} for it, row in zip(items, edited)]


def _gate_references(rows: list[dict], index: int) -> list[dict]:
    """The citations the extractor found, each matched (or not) to a row of the
    legal-context base. Law and article are editable so an unresolved one can
    be fixed here; `commit` re-resolves anything that changed."""
    if not rows:
        st.caption("استنادی در متن یافت نشد — می‌توانید یکی اضافه کنید یا ادامه دهید.")
    edited = st.data_editor(
        [{"نگه‌داری": bool(r.get("keep", True)), "قانون": r.get("law", ""),
          "ماده": r.get("article", "") or "", "نحوهٔ استناد": r.get("context", ""),
          "متصل": "✓" if r.get("resolved") else "✕"} for r in rows],
        use_container_width=True, hide_index=True, num_rows="dynamic", key=f"wf_ref_{index}",
        column_config={"متصل": st.column_config.TextColumn(disabled=True, width="small")},
    )
    out = []
    for i, row in enumerate(edited):
        base = rows[i] if i < len(rows) else {}
        law, art = str(row.get("قانون") or "").strip(), str(row.get("ماده") or "").strip()
        if not law:
            continue
        changed = law != base.get("law") or art != (base.get("article") or "")
        out.append({
            **base, "law": law, "article": art, "context": str(row.get("نحوهٔ استناد") or "").strip(),
            "keep": bool(row.get("نگه‌داری", True)),
            # a hand-edited citation loses its old link; commit re-resolves it
            "ref_id": None if changed else base.get("ref_id"),
            "resolved": False if changed else bool(base.get("resolved")),
        })
    return out


def _gate_labels(labels: list[str], index: int) -> list[str]:
    from app.rag.taxonomy import leaves

    options = list(dict.fromkeys([*labels, *leaves()]))
    return st.multiselect(
        "برچسب‌ها — بردارید یا اضافه کنید", options, default=labels,
        key=f"wf_lbl_{index}", accept_new_options=True,
    )


def _edit_gate(message: dict, index: int) -> None:
    """The confirmation an edit has to pass before it reaches the archive.

    `propose_edit` wrote nothing — this is the only place `entryedit.apply`
    is called. One field, the current value beside the new one, and no table:
    bulk field editing belongs to section ۱۷.
    """
    proposal = message.get("pending_edit")
    if not proposal:
        return

    if message.get("edit_done"):
        st.markdown(
            f"<div class='ack'>ثبت شد — {esc(proposal['field_fa'])}: "
            f"{esc(proposal['new_text'])}</div>", unsafe_allow_html=True)
        return
    if message.get("edit_cancelled"):
        st.markdown("<div class='ack'>ویرایش انجام نشد.</div>", unsafe_allow_html=True)
        return

    verb = "افزودن به" if proposal.get("op") == "append" else "تغییر"
    card(
        f"<h4>{esc(verb)} «{esc(proposal['field_fa'])}»</h4>"
        + kv([
            ("مدخل", esc(proposal.get("entry_title") or proposal["entry_id"])),
            ("مقدار فعلی", esc(proposal["old_text"])),
            ("مقدار جدید", esc(proposal["new_text"])),
        ])
    )

    left, right = st.columns(2)
    if left.button("تأیید و ثبت", key=f"edit_ok_{index}", type="primary", use_container_width=True):
        async def _apply():
            async with session() as s:
                return await entryedit.apply(s, proposal)

        try:
            saved = aio.run(_apply())
        except Exception as error:  # noqa: BLE001 — shown, not raised into the chat
            st.error(f"ثبت نشد — {error}")
            return
        message["edit_done"] = True
        data.refresh()
        # The entry just edited is what the conversation is working on, so
        # «نشانش بده» or another change lands on it without naming it again.
        _focus("entry", proposal["entry_id"], (saved or {}).get("title") or proposal.get("entry_title") or "")
        st.rerun()

    if right.button("انصراف", key=f"edit_no_{index}", use_container_width=True):
        message["edit_cancelled"] = True
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
        # The dialogue's punctuation: one line confirming what an answer did,
        # between one question and the next.
        if message.get("kind") == "ack":
            st.markdown(f"<div class='ack'>{esc(message.get('text', ''))}</div>",
                        unsafe_allow_html=True)
            return

        if message.get("pending_edit"):
            _edit_gate(message, index)

        intent = message.get("intent")
        if intent:
            st.markdown(
                f"<span class='intent-badge {intent}'>{esc(_INTENT_FA.get(intent, intent))}</span>",
                unsafe_allow_html=True,
            )
        if intent == "archive":
            if _latest_for_run(index, message.get("run_id")):
                _render_pipeline(cfg, message, index)
            else:
                if message.get("text"):
                    st.markdown(
                        f"<div class='answer'>{esc(message['text']).replace(chr(10), '<br>')}</div>",
                        unsafe_allow_html=True,
                    )
                st.caption("ادامهٔ این ثبت در پیام‌های بعدی است.")
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
        if message.get("entity_profile"):
            # An answer that came from the party table keeps its ticket when the
            # transcript is redrawn, instead of collapsing back into prose.
            components.entity_ticket(message["entity_profile"], key_prefix=f"hist_entity_{index}")
        elif body:
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
        if message.get("case_hits") and not message.get("entity_profile"):
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
        if message.get("similar_cases"):
            offset = len(message.get("law_refs") or message.get("case_hits") or message.get("contexts") or [])
            _show_similar(message, offset=offset, key_prefix=f"history_{index}")
        if message.get("stats"):
            with st.expander("دادهٔ خام"):
                st.json(message["stats"])
        if message.get("provenance"):
            components.provenance_panel(message["provenance"], key_prefix=f"history_{index}")
        elif message.get("model"):
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
    # A conversation-mode filing that is waiting for an answer takes the
    # message before the router does — unless the user pinned another intent.
    pending = _pending_conversation() if forced in ("auto", "archive") else None
    with st.chat_message("assistant", avatar="⚖️"):
        try:
            if pending:
                st.markdown(
                    f"<span class='intent-badge archive'>{esc(_INTENT_FA['archive'])} — پاسخ در گفتگو</span>",
                    unsafe_allow_html=True,
                )
                _conversation_turn(cfg, pending, text)
                intent = "archive"
                decision = None
            else:
                with st.status("در حال تشخیص نوع پیام…", expanded=False) as status:
                    # The router needs a session: a message naming someone
                    # the archive knows is answered from the party table, and
                    # that lookup is what decides the route.
                    async def _route_it():
                        async with session() as s:
                            return await route(
                                _active_llm(cfg), text,
                                forced=None if forced == "auto" else forced,
                                session=s,
                            )

                    decision = aio.run(_route_it())
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
            # Same vocabulary the FastAPI /assistant path uses — the decision
            # comes from one `route()`, only the execution differs (streamed
            # here, a dict there).
            if pending:
                pass
            elif intent == "unclear":
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
            elif intent == "agent":
                _answer_with_agent(cfg, text)
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
            res = await answer_law_question(s, _active_llm(cfg), text, max_tokens=cfg.get("max_tokens") or 1400)
            await similar_stage(s, _active_llm(cfg), "law", text, res)
            await attach_provenance(s, _active_llm(cfg), "law", text, res, source="ui")
            return res

    with st.spinner("در حال جستجو در پایگاه قوانین و پرونده‌های مشابه…"):
        result = aio.run(_go())
    components.reasoning_panel(result.get("reasoning"))
    st.markdown(f"<div class='answer'>{esc(result.get('answer',''))}</div>", unsafe_allow_html=True)
    _show_similar(result, offset=len(result.get("refs") or []), key_prefix="live_law")
    components.provenance_panel(result.get("provenance"), key_prefix="live_law")
    components.steps_panel(result.get("steps", []))
    _say("assistant", intent="law", text=result.get("answer", ""), law_refs=result.get("refs", []),
         question=text, model=result.get("model"), provenance=result.get("provenance"),
         reasoning=result.get("reasoning"),
         **{k: result[k] for k in ("similar_cases", "lessons", "advice") if result.get(k)})


def _answer_from_cases(cfg: dict, text: str) -> None:
    """The «case archive» route: structured case records, answer cites [n]."""
    from app.rag.casebase import answer_case_question

    async def _go():
        async with session() as s:
            res = await answer_case_question(s, _active_llm(cfg), text, max_tokens=cfg.get("max_tokens") or 1400)
            await similar_stage(s, _active_llm(cfg), "cases", text, res)
            await attach_provenance(s, _active_llm(cfg), "cases", text, res, source="ui")
            return res

    with st.spinner("در حال جستجو در بایگانی پرونده‌ها…"):
        result = aio.run(_go())
    components.reasoning_panel(result.get("reasoning"))

    # A question about a named person or organisation is answered from the
    # party table, so it has a record to show rather than a paragraph to read:
    # the same ledger ticket the dashboard is drawn in, every case clickable.
    if result.get("entity"):
        components.entity_ticket(result["entity_profile"], key_prefix="live_entity")
    else:
        st.markdown(f"<div class='answer'>{esc(result.get('answer',''))}</div>", unsafe_allow_html=True)
    _show_similar(result, offset=len(result.get("cases") or []), key_prefix="live_cases")
    components.provenance_panel(result.get("provenance"), key_prefix="live_cases")
    components.steps_panel(result.get("steps", []))
    hits = [
        {k: c.get(k) for k in ("id", "case_number", "title", "case_type", "insurance_line", "status_fa", "outcome")}
        for c in result.get("cases", [])
    ]
    _say("assistant", intent="cases", text=result.get("answer", ""), case_hits=hits, model=result.get("model"),
         provenance=result.get("provenance"), reasoning=result.get("reasoning"),
         entity_profile=result.get("entity_profile"),
         **{k: result[k] for k in ("similar_cases", "lessons", "advice") if result.get(k)})


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
    "review": "تأیید یک‌باره", "steps": "گام‌به‌گام", "auto": "خودکار", "conversation": "گفتگویی",
}


def _controls(cfg: dict) -> None:
    """Per-message choices: what kind of message this is, and — for a new
    entry — how much the pipeline stops for you. Model and STT choices are
    settings and live in the left panel."""
    if st.session_state.pop("compose_intent", None) == "archive":
        st.session_state["agent_intent"] = "archive"
    left, right, speaker = st.columns([2, 2, 1.4])
    with speaker:
        speak.toggle()
    with left:
        st.selectbox(
            "نوع پیام", ["auto", "query", "law", "cases", "agent", "archive", "analytics", "chat"],
            format_func=lambda k: "تشخیص خودکار" if k == "auto" else _INTENT_FA[k],
            key="agent_intent", label_visibility="collapsed",
            help=(
                "به‌صورت پیش‌فرض سامانه خودش تشخیص می‌دهد؛ می‌توانید دستی تعیین کنید. "
                "«پژوهش عاملی»: مدل خودش با ابزارهای فقط‌خواندنی در آرشیو جستجو می‌کند."
            ),
        )
    with right:
        st.selectbox(
            "حالت ثبت مدخل", ["conversation", "review", "steps", "auto"],
            format_func=lambda k: _WF_MODE_FA[k],
            key="wf_mode", label_visibility="collapsed",
            help=(
                "«گفتگویی» (پیش‌فرض): دستیار یک‌به‌یک می‌پرسد و هر پاسخ یک نوبت "
                "در همین گفتگوست. «تأیید یک‌باره»: همه‌چیز اجرا می‌شود و یک‌بار برای "
                "بازبینی می‌ایستد. «گام‌به‌گام»: در هر مرحله می‌ایستد. «خودکار»: بدون "
                "توقف ثبت می‌کند."
            ),
        )


def _active_llm(cfg: dict):
    """The model from the left panel."""
    return cfg["llm"]


def _speak_latest() -> None:
    """Read the newest assistant turn aloud, when the speaker is on.

    Keyed on the turn's position in the transcript, so a rerun — Streamlit
    re-executes the whole script on every interaction — replays nothing.
    """
    history = _history()
    for index in range(len(history) - 1, -1, -1):
        message = history[index]
        if message.get("role") != "assistant":
            continue
        text = message.get("prompt") or message.get("text") or ""
        if text:
            speak.say(text, seq=index)
        return


def _voice_command(cfg: dict, spoken: str) -> bool:
    """Act on a spoken command instead of sending it as a message.

    Dictation has no buttons: someone filing a case by voice cannot reach for
    «گفتگوی جدید» in the corner of the screen. `app/rag/voice.py` decides what
    counts as a command — deliberately only phrases that would be useless as a
    message, so nothing a person actually dictates is ever swallowed.
    """
    command = voice.command_of(spoken)
    if command is None:
        return False

    if command == "new_chat":
        st.session_state["chat"] = []
        st.session_state.pop("pending_run", None)
    elif command == "new_case":
        st.session_state["agent_intent"] = "archive"
    elif command == "stop":
        run_id = st.session_state.pop("pending_run", None)
        if run_id:
            _wf_abandon(run_id)
    elif command == "repeat":
        st.session_state["_speak_again"] = True

    if command != "new_chat":
        # The acknowledgement is spoken as well as shown, so a voice-only user
        # hears that the command landed instead of watching a silent screen.
        _say("assistant", kind="ack", text=voice.ACK_FA.get(command, ""))
    return True


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
            # Watch it being transcribed rather than waiting behind a spinner.
            # Gemini's live model settles a phrase over several passes —
            # «وضعیت» becomes «وضعیت مالی شرکت» becomes the whole question — and
            # watching that happen is the difference between dictation that
            # feels answerable and a progress bar. Backends that cannot stream
            # emit a single `done` and simply appear at the end.
            #
            # The events are: `interim` replaces the phrase still being heard,
            # `final` settles it, and `done` carries everything joined. So the
            # settled phrases are kept and the interim one is only ever shown
            # after them — appending interims would repeat every correction.
            settled: list[str] = []
            spoken = ""
            try:
                with st.chat_message("user", avatar="🎙️"):
                    heard = st.empty()
                    for event in aio.iterate(stt.stream(
                        audio.getvalue(), "audio.wav",
                        choice=st.session_state.get("agent_stt"),
                    )):
                        text = (event.get("text") or "").strip()
                        kind = event.get("type")
                        if kind == "done":
                            spoken = text
                            break
                        if not text:
                            continue
                        if kind == "final":
                            settled.append(text)
                            shown = " ".join(settled)
                        else:
                            shown = " ".join([*settled, text])
                        heard.markdown(
                            f"<div class='bubble-user' style='opacity:.7'>{esc(shown)}</div>",
                            unsafe_allow_html=True,
                        )
                    heard.empty()
            except Exception as error:  # noqa: BLE001
                components.error_box(error)
                return
            # `done` is authoritative; the settled phrases are the fallback for
            # a stream that timed out before sending one.
            spoken = (spoken or " ".join(settled)).strip()
            if not spoken:
                st.warning("چیزی شنیده نشد.")
            elif _voice_command(cfg, spoken):
                st.rerun()
            else:
                _submit(cfg, spoken)

    if typed:
        _submit(cfg, typed)


def _home(cfg: dict) -> None:
    """The empty-chat screen: what this assistant can be asked, ready to click.

    The prompts come from `app/ui/prompts.py`, which is the same list the evals
    run — so everything advertised here is something that is actually checked,
    and a prompt cannot quietly rot into a demo that no longer works. Each one
    carries a note saying what a right answer looks like, on hover.
    """
    from app.demo.stages import STAGES
    from app.ui import prompts as lib

    st.caption("بنویسید یا بگویید — سامانه خودش تشخیص می‌دهد. یا یکی از این نمونه‌ها را بزنید:")

    for group in lib.GROUPS:
        st.markdown(
            f"<div class='ask-count' style='margin-top:10px'>{esc(group.title)}</div>"
            f"<div class='meta' style='margin-bottom:4px'>{esc(group.blurb)}</div>",
            unsafe_allow_html=True,
        )
        # A follow-up is shown attached to what it follows, dimmed, because on
        # its own it refines nothing.
        for index, prompt in enumerate(group.prompts):
            label = ("↳ " if prompt.follows else "") + prompt.text
            if len(label) > 92:
                label = label[:92] + "…"
            if st.button(label, key=f"lib_{group.id}_{index}", use_container_width=True,
                         help=prompt.note, disabled=prompt.follows and not _history()):
                if prompt.intent:
                    st.session_state["agent_intent"] = prompt.intent
                _submit(cfg, prompt.text)

    runnable = [stage for stage in STAGES if stage.prompts]
    if runnable:
        with st.expander("مراحل نمایش — هر مرحله چند پرسش پشت سر هم را اجرا می‌کند"):
            for stage in runnable:
                if st.button(stage.title, key=f"stage_{stage.id}", use_container_width=True,
                             help=stage.blurb):
                    st.session_state["stage"] = {"id": stage.id, "step": 0}
                    st.rerun()


def _stage_bar(cfg: dict) -> None:
    """A demo stage in progress: which prompt is next, and one button to send it
    with the intent and run mode the stage prescribes."""
    active = st.session_state.get("stage")
    if not active:
        return
    from app.demo.stages import BY_ID

    stage = BY_ID.get(active.get("id"))
    if stage is None:
        st.session_state.pop("stage", None)
        return
    step = int(active.get("step", 0))
    if step >= len(stage.prompts):
        st.success(f"مرحلهٔ «{stage.title}» تمام شد." + (" بخش‌های مرتبط: " + "، ".join(stage.show) if stage.show else ""))
        if st.button("پایان مرحله", key="stage_done"):
            st.session_state.pop("stage", None)
            st.rerun()
        return
    prompt = stage.prompts[step]
    with st.container(border=True):
        cols = st.columns([4, 1])
        cols[0].markdown(
            f"**{esc(stage.title)}** — گام {fa_num(step + 1)} از {fa_num(len(stage.prompts))}"
            + (f"<div class='meta'>{esc(prompt.note)}</div>" if prompt.note else "")
            + f"<div class='meta' style='white-space:pre-wrap'>{esc(prompt.text[:160])}{'…' if len(prompt.text) > 160 else ''}</div>",
            unsafe_allow_html=True,
        )
        if cols[1].button("ارسال این گام", key=f"stage_send_{stage.id}_{step}", type="primary", use_container_width=True):
            if not prompt.reply:
                st.session_state["agent_intent"] = prompt.intent or "auto"
                if prompt.mode:
                    st.session_state["wf_mode"] = prompt.mode
            st.session_state["stage"] = {"id": stage.id, "step": step + 1}
            _submit(cfg, prompt.text)
        if cols[1].button("لغو", key=f"stage_cancel_{stage.id}_{step}", use_container_width=True):
            st.session_state.pop("stage", None)
            st.rerun()


def _threads() -> None:
    """The conversation list — reopen one, or delete it.

    A thread is a row now, so it survives a reload and can be removed. The
    answers it produced stay in `assistant_answers` with their provenance:
    deleting a chat clears the user's list, not the archive's record of what
    was asked.
    """
    async def _recent():
        async with session() as s:
            return await conversations.recent(s, limit=20)

    rows = aio.run(_recent())
    if not rows:
        components.empty("هنوز گفتگویی ذخیره نشده است.")
        return

    current = st.session_state.get("conversation_id")
    st.caption("گفتگوهای پیشین — روی هرکدام بزنید تا باز شود.")
    for row in rows:
        cols = st.columns([6, 1])
        label = row["title"]
        if row.get("focus", {}).get("label"):
            label += f" · {row['focus']['label']}"
        mark = "▸ " if row["id"] == current else ""
        if cols[0].button(f"{mark}{label}  ({fa_num(row.get('messages', 0))} پیام)",
                          key=f"thread_{row['id']}", use_container_width=True):
            _load_conversation(row["id"])
            st.session_state["show_threads"] = False
            st.rerun()
        if cols[1].button("حذف", key=f"thread_del_{row['id']}", use_container_width=True):
            async def _drop(cid=row["id"]):
                async with session() as s:
                    return await conversations.remove(s, cid)

            aio.run(_drop())
            if row["id"] == current:
                st.session_state.pop("conversation_id", None)
                st.session_state["chat"] = []
            st.rerun()


def render(cfg: dict, state: dict) -> None:
    """Chips when the conversation is empty, the transcript once it isn't, and
    the composer. Nothing else — this screen is a chat, and the model and
    retrieval controls already live in the left panel."""
    history = _history()

    _stage_bar(cfg)

    if not history:
        _home(cfg)
    else:
        head = st.columns([4, 1, 1])
        if head[1].button("گفتگوی جدید", key="chat_new", use_container_width=True):
            st.session_state.pop("conversation_id", None)
            st.session_state["chat"] = []
            st.session_state["chat_focus"] = {}
            st.rerun()
        if head[2].button("گفتگوها", key="chat_list", use_container_width=True):
            st.session_state["show_threads"] = not st.session_state.get("show_threads")
            st.rerun()

    if st.session_state.get("show_threads"):
        _threads()

    for index, message in enumerate(history):
        _render(cfg, message, index)

    _source_preview(cfg)
    _answer_pending(cfg)
    _speak_latest()

    _controls(cfg)
    _composer(cfg)

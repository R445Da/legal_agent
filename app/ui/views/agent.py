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
from app.ui import aio, components, data
from app.ui.resources import session
from app.ui.theme import card, case_id, chips, esc, fa_num, kv, stamp

_EXAMPLES = [
    "چند پرونده کارگری داریم؟",
    "در پرونده کالای معیوب دادگاه چه تصمیمی گرفت؟",
    "پرونده‌های آقای کریمی را نشان بده",
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
                label="آمادهٔ بازبینی" if awaiting else "خط لوله آغاز شد",
                state="complete",
            )
    _say("assistant", intent="archive", run_id=view["id"])


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
    "classify": "تشخیص نوع", "extract": "استخراج ساختاریافته", "timeline": "خط زمان",
    "similar": "پرونده‌های مشابه", "labels": "برچسب‌ها", "commit": "ثبت در آرشیو",
}
_STEP_ORDER = ["classify", "extract", "timeline", "similar", "labels", "commit"]
_GATE_ACTION = {
    "extract": "تأیید فیلدها و ادامه", "timeline": "تأیید خط زمان و ادامه",
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


def _stepper(view: dict) -> None:
    by_id = {s["step_id"]: s for s in view["steps"]}
    rows = ""
    for seq, sid in enumerate(_STEP_ORDER, start=1):
        step = by_id.get(sid, {"seq": seq, "status": "pending"})
        status = step["status"]
        icon = _WF_ICON.get(status, fa_num(seq))
        ms = f"<span class='wf-ms'> · {fa_num(step['ms'])} م‌ث</span>" if step.get("ms") else ""
        detail = (
            f"<div class='wf-detail{' err' if status == 'failed' else ''}'>"
            f"{esc(step.get('error') or step.get('detail') or '')}</div>"
            if (step.get("detail") or step.get("error")) else ""
        )
        rows += (
            f"<div class='wf-step {status}'><div class='wf-icon'>{icon}</div>"
            f"<div style='flex:1;min-width:0'><div class='wf-label'>{fa_num(seq)}. "
            f"{esc(_STEP_FA[sid])}{ms}</div>{detail}</div></div>"
        )
    st.markdown(f"<div class='card'>{rows}</div>", unsafe_allow_html=True)


def _render_pipeline(cfg: dict, message: dict, index: int) -> None:
    """The archive path: the six-step run, and whichever gate it is waiting on."""
    view = _wf_load(message["run_id"])
    if not view:
        st.error("اجرای خط لوله یافت نشد.")
        return

    _stepper(view)

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
    with st.expander(
        f"ویرایش جزئیات — فیلدها، خط زمان ({fa_num(len(timeline))})، "
        f"مشابه‌ها ({fa_num(len(similar))})، برچسب‌ها ({fa_num(len(labels))})"
    ):
        st.caption("فیلدهای مدخل")
        draft = _edit_fields(draft, index)
        st.caption("خط زمان")
        timeline = _gate_timeline(timeline, index)
        st.caption("پرونده‌های مشابه — تیک موارد نامرتبط را بردارید")
        similar = _gate_similar({"items": similar, "tool_log": payload.get("tool_log")}, index)
        st.caption("برچسب‌ها")
        labels = _gate_labels(labels, index)

    return {"draft": draft, "timeline": timeline, "similar": similar, "labels": labels}


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


def _gate_labels(labels: list[str], index: int) -> list[str]:
    from app.rag.taxonomy import leaves

    options = list(dict.fromkeys([*labels, *leaves()]))
    return st.multiselect(
        "برچسب‌ها — بردارید یا اضافه کنید", options, default=labels,
        key=f"wf_lbl_{index}", accept_new_options=True,
    )


def _render(cfg: dict, message: dict, index: int) -> None:
    if message["role"] == "user":
        with st.chat_message("user", avatar="🧑"):
            st.markdown(f"<div class='bubble-user'>{esc(message['text'])}</div>",
                        unsafe_allow_html=True)
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
                cols = st.columns(3)
                for col, choice, label in zip(
                    cols, ("query", "archive", "analytics"),
                    ("پرسش از آرشیو", "ثبت مطلب", "آمار"),
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
            else:
                _answer_from_archive(cfg, text)
        except Exception as error:  # noqa: BLE001
            # Keep the user's text — store the failure on the turn so it renders
            # as a ret ryable error and is not attempted again automatically.
            turn["error"] = f"{type(error).__name__}: {error}"
        else:
            turn["answered"] = True
    st.rerun()


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
    left, right = st.columns(2)
    with left:
        st.selectbox(
            "نوع پیام", ["auto", "query", "archive", "analytics", "chat"],
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

"""
The archive gate, conducted as a conversation.

`app/rag/workflow.py` stops at a human gate and hands the UI a payload: the
extracted draft, the citations it linked to the law base, the timeline it
built, the prior records it matched, the labels it proposes. The first version
of this screen rendered that payload as `st.data_editor` grids — the whole
record at once, as a spreadsheet, with one «تأیید و ادامه» button underneath.

This module turns the same payload into an ordered list of **questions**. The
chat asks one, the user answers in the composer (or taps a quick reply), and
that answer advances to the next question — so filing a case reads as a
conversation and every answer is its own turn in the transcript. Only when the
queue is exhausted is a single `user_patch` handed back to `workflow.advance`,
so the state machine, its run log and the build console are untouched: this is
a presentation layer over the same gate, not a second pipeline.

A question is a plain dict so it survives in `st.session_state` across reruns:

    id      unique within the gate — also the widget key suffix
    kind    confirm | text        (a confirm may push a `text` follow-up)
    prompt  the Persian question, already numbered where it helps
    chips   quick replies; tapping one sends it as the user's turn
    card    optional HTML shown with the question (the value under discussion)
    free    what free text means here: "value" replaces the value, "ignore"
            treats anything unrecognised as agreement

Nothing here touches the database or the model.
"""

from __future__ import annotations

import streamlit as st

from app.ui.theme import case_id, chips as chip_html, esc, fa_num, timeline as tl_html

_STATE_KEY = "askflow"

# What counts as yes / no / "let me change it". Matched by substring against the
# folded answer, so «تایید می‌کنم» and «تأیید» both land on yes.
_YES = ("تأیید", "تایید", "بله", "بلی", "آری", "اوکی", "اوکیه", "باشه", "درست",
        "صحیح", "موافقم", "ثبت", "نگه", "پیوند بزن", "ok", "yes", "✓")
_NO = ("رد کن", "ردش", "نه", "خیر", "نادرست", "غلط", "اشتباه", "حذف", "پاک",
       "خالی", "پیوند نزن", "بی‌خیال", "بیخیال", "ندارم", "نمی‌دانم", "نمیدانم",
       "no", "✕")
_EDIT = ("اصلاح", "تغییر", "ویرایش", "عوض", "یکی‌یکی", "یکی یکی", "خودم")

_SKIP = ("رد کن", "نمی‌دانم", "نمیدانم", "ندارم", "بعدا", "بعداً", "بگذر", "skip")


def _fold(text: str) -> str:
    return (text or "").replace("‌", " ").strip().lower()


def _says(text: str, words: tuple[str, ...]) -> bool:
    folded = _fold(text)
    return any(_fold(w) in folded for w in words)


# --------------------------------------------------------------------------- #
# Cards — the value under discussion, drawn in the ledger vocabulary
# --------------------------------------------------------------------------- #
def _card(body: str) -> str:
    return f"<div class='ask-card'>{body}</div>"


def _refs_card(rows: list[dict]) -> str:
    items = []
    for row in rows:
        cite = row.get("law") or ""
        if row.get("article"):
            cite = f"مادهٔ {fa_num(row['article'])} {cite}"
        linked = ("<span class='stamp teal'><span class='dotc'></span>متصل</span>"
                  if row.get("resolved") else
                  "<span class='stamp review'><span class='dotc'></span>بدون اتصال</span>")
        items.append(f"<div class='ask-row'><span>{esc(cite)}</span>{linked}</div>")
    return _card("".join(items))


def _similar_card(rows: list[dict]) -> str:
    from app.rag.casebase import STATUS_FA

    items = []
    for row in rows:
        outcome = (row.get("outcome") or "").strip()
        # `outcome` is Persian prose for most rows, but a matched entry whose
        # only recorded outcome is its status arrives as the schema's English
        # enum. Runs recorded before that was fixed upstream still carry it, so
        # translate on the way to the screen too.
        outcome = STATUS_FA.get(outcome, outcome)
        items.append(
            f"<div class='ask-row'><span>{esc(row.get('title') or 'بدون عنوان')}</span>"
            f"<span class='meta'>{esc(outcome[:60])}</span></div>"
        )
    return _card("".join(items))


def _labels_card(labels: list[str]) -> str:
    return _card(chip_html(labels, teal=True) if labels else
                 "<div class='meta'>برچسبی پیشنهاد نشد.</div>")


def _value_card(value: str, *, number: bool = False) -> str:
    if number:
        return _card(case_id(value))
    return _card(f"<div class='ask-value'>{esc(value)}</div>")


# --------------------------------------------------------------------------- #
# Building the queue
# --------------------------------------------------------------------------- #
_ASK_FA = {
    "title": ("عنوان پرونده", "عنوان پرونده را در یک سطر بنویسید."),
    "summary": ("خلاصه", "خلاصهٔ پرونده را در یک یا دو جمله بنویسید."),
    "entities.case_number": ("شمارهٔ کلاسه", "شمارهٔ کلاسه را بفرمایید."),
    "entities.court": ("دادگاه", "نام دادگاه یا شعبه را بفرمایید."),
    "entities.topic": ("موضوع", "موضوع پرونده را بفرمایید."),
}


def _missing_pairs(payload: dict) -> list[tuple[str, str]]:
    """`_missing_required()` round-trips through JSON, so its tuples arrive as
    lists — accept either."""
    out = []
    for item in payload.get("missing") or []:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            out.append((str(item[0]), str(item[1])))
    return out


def _q(qid: str, prompt: str, *, kind: str = "confirm", chips: list[str] | None = None,
       card: str = "", free: str = "ignore", note: str = "") -> dict:
    return {"id": qid, "kind": kind, "prompt": prompt, "chips": chips or [],
            "card": card, "free": free, "note": note}


def _draft_questions(draft: dict, payload: dict) -> list[dict]:
    """The record itself: confirm what was extracted, ask for what was not."""
    queue: list[dict] = []
    missing = {path for path, _ in _missing_pairs(payload)}

    title = (draft.get("title") or "").strip()
    if title:
        queue.append(_q(
            "title", "این متن یک پروندهٔ جدید است. عنوان پرونده را تأیید می‌کنید؟",
            chips=["تأیید", "اصلاح می‌کنم"], card=_value_card(title), free="value",
            note="می‌توانید عنوان درست را مستقیم بنویسید.",
        ))
    else:
        queue.append(_q(
            "title", "عنوانی برای این پرونده پیدا نکردم — چه عنوانی بگذارم؟",
            kind="text", chips=["خودت بساز"], free="value",
        ))

    number = ((draft.get("entities") or {}).get("case_number") or "").strip()
    if number:
        queue.append(_q(
            "entities.case_number", "شمارهٔ کلاسه را این‌طور خواندم — درست است؟",
            chips=["تأیید", "اصلاح می‌کنم"], card=_value_card(number, number=True),
            free="value",
        ))
    else:
        queue.append(_q(
            "entities.case_number", "شمارهٔ کلاسه را پیدا نکردم — بفرمایید.",
            kind="text", chips=["ندارم"], free="value",
        ))

    for path, fa in _missing_pairs(payload):
        if path in {"title", "entities.case_number"}:
            continue
        _, prompt = _ASK_FA.get(path, (fa, f"{fa} را بفرمایید."))
        queue.append(_q(path, f"{prompt}", kind="text", chips=["ندارم"], free="value"))

    summary = (draft.get("summary") or "").strip()
    if summary and "summary" not in missing:
        queue.append(_q(
            "summary", "خلاصه‌ای که نوشتم این است — تأیید می‌کنید؟",
            chips=["تأیید", "اصلاح می‌کنم"], card=_value_card(summary), free="value",
        ))
    return queue


def _refs_questions(rows: list[dict]) -> list[dict]:
    if not rows:
        return []
    unresolved = sum(1 for r in rows if not r.get("resolved"))
    prompt = f"{fa_num(len(rows))} استناد قانونی یافتم؛ نگه دارم؟"
    if unresolved:
        prompt += f" ({fa_num(unresolved)} مورد به پایگاه قوانین متصل نشد)"
    return [_q("refs", prompt, chips=["نگه دار", "یکی‌یکی", "حذف کن"],
               card=_refs_card(rows))]


def _timeline_questions(rows: list[dict]) -> list[dict]:
    if not rows:
        return []
    return [_q(
        "timeline", f"{fa_num(len(rows))} رویداد روی خط زمان نشستند — تأیید می‌کنید؟",
        chips=["تأیید", "خالی کن"], card=_card(tl_html(rows)),
    )]


def _similar_questions(rows: list[dict]) -> list[dict]:
    if not rows:
        return []
    return [_q(
        "similar", f"{fa_num(len(rows))} پروندهٔ مشابه پیدا کردم — پیوند بزنم؟",
        chips=["پیوند بزن", "یکی‌یکی", "پیوند نزن"], card=_similar_card(rows),
    )]


def _labels_questions(labels: list[str]) -> list[dict]:
    return [_q(
        "labels",
        ("برچسب‌های این مدخل را این‌ها می‌گذارم — تأیید می‌کنید؟" if labels
         else "برچسبی پیشنهاد نشد — خودتان برچسبی می‌گذارید؟"),
        chips=["تأیید", "تغییر می‌دهم"] if labels else ["بی‌برچسب باشد"],
        card=_labels_card(labels), free="value",
        note="برچسب‌ها را با ویرگول جدا کنید.",
    )]


def _commit_question() -> dict:
    return _q("commit", "همه‌چیز آماده است. در آرشیو ثبت کنم؟",
              chips=["ثبت کن", "لغو"])


def questions_for(step_id: str, payload: dict, mode: str) -> list[dict]:
    """The gate, as an ordered conversation.

    In `review` mode the run stops once, at `labels`, with the whole record in
    the payload — so that one gate becomes the full sequence. In `steps` mode
    each gate contributes only its own questions.
    """
    review = step_id == "labels" and payload.get("mode") == "review"
    if review:
        draft = dict(payload.get("draft") or {})
        return [
            *_draft_questions(draft, payload),
            *_refs_questions(payload.get("references") or []),
            *_timeline_questions(payload.get("timeline") or []),
            *_similar_questions(payload.get("similar") or []),
            *_labels_questions(payload.get("labels") or []),
            _commit_question(),
        ]
    if step_id == "extract":
        return _draft_questions(dict(payload or {}), {})
    if step_id == "references":
        return _refs_questions((payload or {}).get("rows") or [])
    if step_id == "timeline":
        return _timeline_questions((payload or {}).get("rows") or [])
    if step_id == "similar":
        return _similar_questions((payload or {}).get("items") or [])
    if step_id == "labels":
        return [*_labels_questions((payload or {}).get("labels") or []), _commit_question()]
    return []


# --------------------------------------------------------------------------- #
# The dialogue state
# --------------------------------------------------------------------------- #
def begin(view: dict, *, mode: str) -> dict | None:
    """Open a conversation for whichever gate `view` is waiting on.

    Returns the state, or None when the run is not awaiting anything (it
    committed, failed, or is still running) — the caller then has nothing to
    ask.
    """
    awaiting = next((s for s in view.get("steps") or []
                     if s["status"] == "awaiting_input"), None)
    if awaiting is None:
        clear()
        return None

    payload = awaiting.get("payload") or {}
    step_id = awaiting["step_id"]
    queue = questions_for(step_id, payload, mode)
    if not queue:
        queue = [_commit_question()]

    # Which parts of `WorkflowState` this gate is allowed to write back.
    # `advance()` applies the patch with `setattr`, so a key present but empty
    # *erases* what an earlier step produced: a `steps`-mode timeline gate that
    # returned `draft: {}` would wipe the extraction. Only the sections the gate
    # actually asked about go back.
    owns = {
        "extract": ["draft"],
        "references": ["references"],
        "timeline": ["timeline"],
        "similar": ["similar"],
        "labels": ["labels"],
    }.get(step_id, [])
    if step_id == "labels" and payload.get("mode") == "review":
        owns = ["draft", "references", "timeline", "similar", "labels"]

    state = {
        "run_id": view["id"],
        "step_id": step_id,
        "cursor": 0,
        "queue": queue,
        "owns": owns,
        # the working copy the answers land in, and what `patch()` reads back
        "draft": dict(payload.get("draft") or (payload if step_id == "extract" else {})),
        "references": list(payload.get("references") or payload.get("rows") or []
                           if step_id in {"labels", "references"} else []),
        "timeline": list(payload.get("timeline") or payload.get("rows") or []
                         if step_id in {"labels", "timeline"} else []),
        "similar": list(payload.get("similar") or payload.get("items") or []
                        if step_id in {"labels", "similar"} else []),
        "labels": list(payload.get("labels") or []),
        "cancelled": False,
    }
    state["draft"].setdefault("entities", {})
    st.session_state[_STATE_KEY] = state
    return state


def state() -> dict | None:
    return st.session_state.get(_STATE_KEY)


def clear() -> None:
    st.session_state.pop(_STATE_KEY, None)


def active(run_id: str | None = None) -> bool:
    stt = state()
    if not stt or stt["cursor"] >= len(stt["queue"]):
        return False
    return run_id is None or stt["run_id"] == run_id


def current() -> dict | None:
    stt = state()
    if not stt or stt["cursor"] >= len(stt["queue"]):
        return None
    return stt["queue"][stt["cursor"]]


def progress() -> tuple[int, int]:
    stt = state()
    if not stt:
        return (0, 0)
    return (min(stt["cursor"] + 1, len(stt["queue"])), len(stt["queue"]))


def record() -> dict:
    """The record as it stands — the draft plus whatever the answers changed."""
    stt = state()
    return (stt or {}).get("draft") or {}


# --------------------------------------------------------------------------- #
# Applying an answer
# --------------------------------------------------------------------------- #
def _set_path(stt: dict, path: str, value: str) -> None:
    if path.startswith("entities."):
        stt["draft"].setdefault("entities", {})[path.split(".", 1)[1]] = value
    else:
        stt["draft"][path] = value


def _insert_follow_ups(stt: dict, questions: list[dict]) -> None:
    at = stt["cursor"] + 1
    stt["queue"][at:at] = questions


def _per_item_refs(stt: dict) -> list[dict]:
    out = []
    for i, row in enumerate(stt["references"]):
        cite = row.get("law") or ""
        if row.get("article"):
            cite = f"مادهٔ {fa_num(row['article'])} {cite}"
        out.append(_q(f"refs:{i}", f"«{cite}» را نگه دارم؟",
                      chips=["نگه دار", "حذف کن"]))
    return out


def _per_item_similar(stt: dict) -> list[dict]:
    return [
        _q(f"similar:{i}", f"«{row.get('title') or 'بدون عنوان'}» را پیوند بزنم؟",
           chips=["پیوند بزن", "پیوند نزن"])
        for i, row in enumerate(stt["similar"])
    ]


def answer(text: str) -> dict:
    """Apply the user's turn to the current question.

    Returns `{"ack": str, "finished": bool, "cancelled": bool}` — `ack` is the
    assistant's one-line acknowledgement, and `finished` means the queue is
    exhausted and the caller should hand `patch()` to `workflow.advance`.
    """
    stt = state()
    question = current()
    if not stt or question is None:
        return {"ack": "", "finished": True, "cancelled": False}

    qid, kind, free = question["id"], question["kind"], question.get("free", "ignore")
    said = (text or "").strip()
    ack = ""

    yes, no, edit = _says(said, _YES), _says(said, _NO), _says(said, _EDIT)
    # «رد کن» reads as both a no and an edit request; no wins.
    if no:
        edit = False

    # --- the record's own fields ------------------------------------------- #
    if qid in _ASK_FA or qid in {"title", "summary"} or qid.startswith("entities."):
        label = _ASK_FA.get(qid, (qid, ""))[0]
        if kind == "text" or (free == "value" and not (yes or no or edit)):
            if _says(said, _SKIP) or no:
                ack = f"{label} را خالی می‌گذارم."
            else:
                _set_path(stt, qid, said)
                ack = f"{label} ثبت شد."
        elif edit:
            _insert_follow_ups(stt, [_q(
                qid, _ASK_FA.get(qid, (label, f"{label} را بنویسید."))[1],
                kind="text", free="value",
            )])
            ack = "بفرمایید."
        elif no:
            _set_path(stt, qid, "")
            ack = f"{label} را برداشتم."
        else:
            ack = "تأیید شد."

    # --- citations --------------------------------------------------------- #
    elif qid == "refs":
        if edit:
            _insert_follow_ups(stt, _per_item_refs(stt))
            ack = "یکی‌یکی می‌پرسم."
        elif no:
            stt["references"] = [{**r, "keep": False} for r in stt["references"]]
            ack = "استنادها را نگه نمی‌دارم."
        else:
            stt["references"] = [{**r, "keep": True} for r in stt["references"]]
            ack = f"{fa_num(len(stt['references']))} استناد نگه داشته شد."
    elif qid.startswith("refs:"):
        i = int(qid.split(":")[1])
        if i < len(stt["references"]):
            stt["references"][i] = {**stt["references"][i], "keep": not no}
        ack = "حذف شد." if no else "نگه داشته شد."

    # --- timeline ---------------------------------------------------------- #
    elif qid == "timeline":
        if no:
            stt["timeline"] = []
            ack = "خط زمان خالی شد."
        else:
            ack = f"{fa_num(len(stt['timeline']))} رویداد تأیید شد."

    # --- prior records ----------------------------------------------------- #
    elif qid == "similar":
        if edit:
            _insert_follow_ups(stt, _per_item_similar(stt))
            ack = "یکی‌یکی می‌پرسم."
        elif no:
            stt["similar"] = [{**s, "keep": False} for s in stt["similar"]]
            ack = "پیوندی نمی‌زنم."
        else:
            stt["similar"] = [{**s, "keep": True} for s in stt["similar"]]
            ack = f"{fa_num(len(stt['similar']))} پرونده پیوند خورد."
    elif qid.startswith("similar:"):
        i = int(qid.split(":")[1])
        if i < len(stt["similar"]):
            stt["similar"][i] = {**stt["similar"][i], "keep": not no}
        ack = "پیوند نخورد." if no else "پیوند خورد."

    # --- labels ------------------------------------------------------------ #
    elif qid == "labels":
        if edit:
            _insert_follow_ups(stt, [_q(
                "labels", "برچسب‌ها را بنویسید (با ویرگول جدا کنید).",
                kind="text", chips=["بی‌برچسب باشد"], free="value",
            )])
            ack = "بفرمایید."
        elif no or _says(said, ("بی‌برچسب",)):
            stt["labels"] = []
            ack = "بدون برچسب."
        elif kind == "text" or not yes:
            parsed = [p.strip() for p in said.replace("،", ",").split(",") if p.strip()]
            if parsed:
                stt["labels"] = parsed
                ack = f"{fa_num(len(parsed))} برچسب ثبت شد."
            else:
                ack = "برچسب‌ها همان ماندند."
        else:
            ack = f"{fa_num(len(stt['labels']))} برچسب تأیید شد."

    # --- the last question -------------------------------------------------- #
    elif qid == "commit":
        if no or _says(said, ("لغو",)):
            stt["cancelled"] = True
            stt["cursor"] = len(stt["queue"])
            return {"ack": "ثبت نشد — این پیش‌نویس را رها کردم.",
                    "finished": True, "cancelled": True}
        ack = "در حال ثبت…"

    stt["cursor"] += 1
    return {"ack": ack, "finished": stt["cursor"] >= len(stt["queue"]),
            "cancelled": False}


def patch() -> dict:
    """What the whole conversation adds up to, in `workflow.advance`'s shape.

    Only the sections this gate owns (see `begin()`): `advance()` assigns every
    key it is handed straight onto the state, so returning a section the gate
    never asked about would overwrite it with an empty one.
    """
    stt = state() or {}
    owns = stt.get("owns") or []
    out: dict = {}
    if "draft" in owns:
        draft = dict(stt.get("draft") or {})
        draft["entities"] = {**(draft.get("entities") or {})}
        out["draft"] = draft
    for key in ("references", "timeline", "similar", "labels"):
        if key in owns:
            out[key] = list(stt.get(key) or [])
    return out

"""
Conversation-mode filing («گفتگویی»): the assistant asks, the user answers.

The other run modes stop the pipeline at a gate and show a form. This mode
stops at the same place — the `labels` slot, once everything has been
extracted — but instead of a `data_editor` it writes a chat message: here is
what I found, here is what is missing, answer in the composer. Each reply is
merged into the draft (a model call with a strict schema where the provider
has one, a regex pass otherwise), the missing list is recomputed, and the
run either asks again or commits through the ordinary `workflow.advance()`.

Everything the dialogue knows lives in `WorkflowState.conversation`, which is
persisted in `runs.state` — so a reload, another tab or the API can pick the
conversation up exactly where it stopped:

    {"turns": [{"role": "assistant", "text", "asked": [paths]},
               {"role": "user", "text", "patch": {...}, "changed": [paths]}],
     "pending": [paths], "skipped": [paths], "rounds": int, "confirmed": bool}
"""

import json
import os
import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.base import LLMProvider
from app.rag import runs, workflow
from app.rag.orchestrator import CASE_TYPES, INSURANCE_LINES, _parse_json
from app.rag.workflow import STEP_IDS, WorkflowState, _missing_required, _payload

MAX_ROUNDS = int(os.environ.get("CONVERSATION_MAX_ROUNDS", "6") or 6)

# The fields the dialogue may fill. Required ones (workflow.REQUIRED_FIELDS)
# are asked for; the rest are accepted when the user volunteers them.
FIELD_FA = {
    "title": "عنوان", "summary": "خلاصه", "entities.case_number": "شمارهٔ پرونده",
    "entities.court": "مرجع رسیدگی", "entities.case_type": "نوع دعوا",
    "entities.insurance_line": "رشتهٔ بیمه", "entities.outcome": "نتیجه",
    "entities.status": "وضعیت", "entities.filed_date": "تاریخ طرح",
    "entities.claim_amount": "مبلغ خواسته",
}
# Labels a user may type before a colon — «شماره پرونده: ۱۴۰۲…».
_LABELS = {
    "title": ("عنوان",), "summary": ("خلاصه", "چکیده"),
    "entities.case_number": ("شماره پرونده", "شمارهٔ پرونده", "شماره‌ی پرونده", "کلاسه", "شماره"),
    "entities.court": ("مرجع", "مرجع رسیدگی", "دادگاه", "شعبه"),
    "entities.case_type": ("نوع دعوا", "نوع"), "entities.insurance_line": ("رشته", "رشتهٔ بیمه", "رشته بیمه"),
    "entities.outcome": ("نتیجه", "رأی", "رای"), "entities.status": ("وضعیت",),
    "entities.filed_date": ("تاریخ", "تاریخ طرح"), "entities.claim_amount": ("مبلغ", "مبلغ خواسته", "خواسته"),
}
_CONFIRM = ("تأیید", "تایید", "درست است", "همین درست است", "ثبت کن", "ثبت شود", "بله", "اوکی", "ok", "confirm", "yes")
_CANCEL = ("انصراف", "لغو", "متوقف", "رها کن", "cancel", "stop")
_SKIP = ("رد شو", "بگذر", "نمی‌دانم", "نمیدانم", "ندارم", "نداریم", "skip", "بعداً")
_CASE_NO = re.compile(r"(?:کلاسه|شماره)\s*(?:ی|ٔ)?\s*(?:پرونده)?\s*[:：]?\s*([0-9۰-۹][0-9۰-۹/\-]{4,19})")
_BARE_NO = re.compile(r"^[0-9۰-۹][0-9۰-۹/\-]{4,19}$")
_LABEL_LINE = re.compile(r"^\s*([^:：\n]{2,24}?)\s*[:：]\s*(.+?)\s*$")
_FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")

MERGE_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "title": {"type": ["string", "null"]},
        "summary": {"type": ["string", "null"]},
        "entities": {
            "type": "object", "additionalProperties": False,
            "properties": {
                "case_number": {"type": ["string", "null"]},
                "court": {"type": ["string", "null"]},
                "case_type": {"type": ["string", "null"]},
                "insurance_line": {"type": ["string", "null"]},
                "outcome": {"type": ["string", "null"]},
                "status": {"type": ["string", "null"], "enum": ["open", "closed", "appeal", "archived", None]},
                "filed_date": {"type": ["string", "null"]},
                "claim_amount": {"type": ["string", "null"]},
            },
            "required": ["case_number", "court", "case_type", "insurance_line", "outcome",
                         "status", "filed_date", "claim_amount"],
        },
        "confirm": {"type": "boolean"},
        "cancel": {"type": "boolean"},
        "note": {"type": ["string", "null"]},
    },
    "required": ["title", "summary", "entities", "confirm", "cancel", "note"],
}

# "merge a user's reply" is the sentinel the offline mock keys on.
_MERGE_SYSTEM = (
    "You merge a user's reply into a draft record of a Persian insurance-law case. "
    "You get the current draft, the fields still missing, and the user's message. "
    "Return JSON only, with exactly these keys: title, summary, entities "
    "{case_number, court, case_type, insurance_line, outcome, status, filed_date, "
    "claim_amount}, confirm, cancel, note. Put a value only where the reply "
    "supplies or corrects one; everything else null. Never invent a value. "
    "confirm=true when the user says the record is right / asks to save it; "
    "cancel=true when they want to stop. case_number is digits as written. "
    "case_type must be one of: " + " | ".join(CASE_TYPES) + ". insurance_line must "
    "be one of: " + " | ".join(INSURANCE_LINES) + ". status is open|closed|appeal|archived."
)


# --------------------------------------------------------------------------- #
# Draft paths
# --------------------------------------------------------------------------- #
def get_path(draft: dict, path: str):
    if path.startswith("entities."):
        return (draft.get("entities") or {}).get(path.split(".", 1)[1])
    return draft.get(path)


def set_path(draft: dict, path: str, value) -> None:
    if path.startswith("entities."):
        draft.setdefault("entities", {})[path.split(".", 1)[1]] = value
    else:
        draft[path] = value


def missing_paths(state: WorkflowState) -> list[str]:
    """Required fields still empty, minus the ones the user chose to skip."""
    skipped = set((state.conversation or {}).get("skipped") or [])
    return [path for path, _fa in _missing_required(state) if path not in skipped]


# --------------------------------------------------------------------------- #
# The assistant's side
# --------------------------------------------------------------------------- #
def propose_message(state: WorkflowState) -> str:
    """Deterministic Persian: what was extracted, what is missing, how to answer."""
    draft = state.draft or {}
    ent = draft.get("entities") or {}
    found: list[str] = []
    if draft.get("title"):
        found.append(f"عنوان: {draft['title']}")
    if ent.get("case_number"):
        found.append(f"شمارهٔ پرونده: {ent['case_number']}")
    if ent.get("court"):
        found.append(f"مرجع: {ent['court']}")
    if ent.get("case_type"):
        found.append(f"نوع دعوا: {ent['case_type']}")
    if ent.get("insurance_line"):
        found.append(f"رشتهٔ بیمه: {ent['insurance_line']}")
    parties = [p.get("name") for p in (draft.get("parties") or []) if isinstance(p, dict) and p.get("name")]
    if parties:
        found.append("طرفین: " + "، ".join(parties[:4]) + (" و…" if len(parties) > 4 else ""))
    refs = draft.get("legal_refs") or []
    if refs:
        found.append(f"{len(refs)} استناد قانونی")
    if ent.get("outcome"):
        found.append(f"نتیجه: {ent['outcome']}")

    missing = missing_paths(state)
    lines: list[str] = []
    if found:
        lines.append("از متن شما این‌ها را برداشتم:")
        lines += [f"• {item}" for item in found]
    else:
        lines.append("از متن شما چیز زیادی برنیامد.")
    if missing:
        names = "، ".join(FIELD_FA.get(p, p) for p in missing)
        lines.append("")
        lines.append(f"این‌ها را پیدا نکردم: {names}.")
        example = "شمارهٔ پرونده: ۱۴۰۲۰۰۱۲۳۴" if "entities.case_number" in missing else f"{FIELD_FA.get(missing[0], missing[0])}: …"
        lines.append(f"در همین گفتگو پاسخ دهید — مثلاً «{example}». اگر ندارید بنویسید «رد شو»؛ "
                     "وقتی همه‌چیز درست بود بنویسید «تأیید» تا ثبت شود.")
    else:
        lines.append("")
        lines.append("چیزی کم نیست. اگر درست است بنویسید «تأیید» تا در آرشیو ثبت شود؛ "
                     "برای اصلاح، فیلد را با دونقطه بنویسید (مثلاً «عنوان: …»).")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# The user's side
# --------------------------------------------------------------------------- #
def _label_to_path(label: str) -> str | None:
    label = " ".join(label.replace("‌", " ").split()).lower()
    for path, names in _LABELS.items():
        if label in names:
            return path
    return None


def regex_merge(reply: str, pending: list[str]) -> dict:
    """Read a reply without a model: labelled lines, a case number anywhere,
    confirm / cancel / skip words, and a bare value for a single pending field."""
    text = (reply or "").strip()
    low = text.lower()
    out: dict = {"patch": {}, "confirm": False, "cancel": False, "skip": []}
    if not text:
        return out
    short = len(text) <= 40
    if any(w in low for w in _CANCEL) and short:
        out["cancel"] = True
        return out
    if short and any(low == w or low.startswith(w) for w in _CONFIRM):
        out["confirm"] = True
    if short and any(w in low for w in _SKIP):
        out["skip"] = list(pending)

    for line in text.splitlines():
        match = _LABEL_LINE.match(line)
        if not match:
            continue
        path = _label_to_path(match.group(1))
        if path:
            value = match.group(2).strip(" .،؛")
            out["patch"][path] = value.translate(_FA_DIGITS) if path == "entities.case_number" else value

    if "entities.case_number" not in out["patch"]:
        match = _CASE_NO.search(text)
        if match:
            out["patch"]["entities.case_number"] = match.group(1).translate(_FA_DIGITS)
        elif _BARE_NO.match(text) and ("entities.case_number" in pending or not pending):
            out["patch"]["entities.case_number"] = text.translate(_FA_DIGITS)

    if not out["patch"] and not out["confirm"] and not out["skip"] and len(pending) == 1 and len(text) <= 160:
        out["patch"][pending[0]] = text.strip(" .،؛")
    return out


def _llm_patch(data: dict) -> dict:
    patch: dict = {}
    for key in ("title", "summary"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            patch[key] = value.strip()
    ent = data.get("entities") if isinstance(data.get("entities"), dict) else {}
    for key, value in (ent or {}).items():
        if isinstance(value, (str, int)) and str(value).strip() and f"entities.{key}" in FIELD_FA:
            patch[f"entities.{key}"] = str(value).strip()
    return patch


async def merge_reply(llm: LLMProvider, state: WorkflowState, reply: str) -> dict:
    """What the reply changes: `{patch: {path: value}, confirm, cancel, skip}`.

    The regex pass settles the cheap cases (a bare number, «تأیید», labelled
    lines). Free text goes to the model with a strict schema when the provider
    honours one; the regex result stays as the fallback when the model call
    fails or returns nothing usable.
    """
    pending = missing_paths(state)
    quick = regex_merge(reply, pending)
    if quick["cancel"] or (quick["confirm"] and not quick["patch"]) or quick["skip"]:
        return quick
    if quick["patch"] and all(path in quick["patch"] for path in pending):
        return quick

    draft = state.draft or {}
    ent = draft.get("entities") or {}
    prompt = (
        "Draft:\n" + json.dumps({
            "title": draft.get("title"), "summary": draft.get("summary"),
            "entities": {k: ent.get(k) for k in ("case_number", "court", "case_type", "insurance_line",
                                                  "outcome", "status", "filed_date", "claim_amount")},
        }, ensure_ascii=False)
        + "\n\nMissing fields: " + ", ".join(pending or ["none"])
        + f"\n\nUser reply:\n{reply}\n\nRespond with JSON only."
    )
    try:
        resp = await llm.generate(
            prompt, system=_MERGE_SYSTEM, max_tokens=600, json_mode=True, reasoning_effort="low",
            json_schema=MERGE_SCHEMA if getattr(llm, "supports_json_schema", False) else None,
        )
        data = _parse_json(resp.text)
    except Exception:  # noqa: BLE001 — the regex pass is the fallback
        data = {}
    merged = {"patch": _llm_patch(data), "confirm": bool(data.get("confirm")),
              "cancel": bool(data.get("cancel")), "skip": []}
    # Anything the regex pass saw for sure (a case number in Persian digits)
    # beats a model that missed it.
    for path, value in quick["patch"].items():
        merged["patch"].setdefault(path, value)
    merged["confirm"] = merged["confirm"] or quick["confirm"]
    return merged


def apply_patch(state: WorkflowState, patch: dict) -> list[str]:
    changed = []
    for path, value in (patch or {}).items():
        if path not in FIELD_FA or value in (None, ""):
            continue
        if get_path(state.draft, path) != value:
            set_path(state.draft, path, value)
            changed.append(path)
    return changed


# --------------------------------------------------------------------------- #
# One turn
# --------------------------------------------------------------------------- #
def _fresh(state: WorkflowState) -> dict:
    return state.conversation or {"turns": [], "pending": [], "skipped": [], "rounds": 0, "confirmed": False}


def is_waiting(view: dict | None) -> bool:
    """True when the run is a conversation paused for the user's reply."""
    if not view or view.get("status") != "awaiting_input":
        return False
    return (view.get("state") or {}).get("mode") == "conversation"


def last_question(view: dict) -> str:
    turns = ((view.get("state") or {}).get("conversation") or {}).get("turns") or []
    for turn in reversed(turns):
        if turn.get("role") == "assistant":
            return turn.get("text", "")
    return ""


async def turn(session: AsyncSession, run_id: str, llm: LLMProvider, reply: str) -> dict:
    """Merge one reply and either re-ask or commit. Returns the run view."""
    view = await runs.load_run(session, run_id)
    if not is_waiting(view):
        raise ValueError("این اجرا در انتظار پاسخ گفتگویی نیست")
    state = WorkflowState.from_dict(view["state"])
    state.raw_text = view["raw_text"]
    state.source = view["source"] or state.source
    conv = _fresh(state)

    result = await merge_reply(llm, state, reply)
    changed = apply_patch(state, result["patch"])
    conv["rounds"] = int(conv.get("rounds", 0)) + 1
    conv["skipped"] = sorted(set(conv.get("skipped") or []) | set(result.get("skip") or []))
    conv["turns"].append({"role": "user", "text": reply, "patch": result["patch"], "changed": changed,
                          "confirm": result["confirm"], "cancel": result["cancel"]})
    state.conversation = conv

    if result["cancel"]:
        await runs.save_state(session, run_id, state.to_dict(), status="abandoned")
        await runs.set_status(session, run_id, "abandoned")
        return await runs.load_run(session, run_id)

    missing = missing_paths(state)
    conv["pending"] = missing
    exhausted = conv["rounds"] >= MAX_ROUNDS
    if (not missing and result["confirm"]) or exhausted:
        conv["confirmed"] = True
        state.conversation = conv
        return await workflow.advance(
            session, run_id, llm,
            user_patch={"draft": state.draft, "conversation": conv, "labels": state.labels},
        )

    question = propose_message(state)
    conv["turns"].append({"role": "assistant", "text": question, "asked": missing})
    state.conversation = conv
    seq = STEP_IDS.index("labels") + 1
    await runs.record_step(
        session, run_id, seq=seq, step_id="labels", label="برچسب‌ها", status="awaiting_input",
        detail="در انتظار پاسخ شما در گفتگو" + (f" — {len(changed)} فیلد به‌روز شد" if changed else ""),
        payload=_payload("labels", state),
    )
    await runs.save_state(session, run_id, state.to_dict(), status="awaiting_input")
    return await runs.load_run(session, run_id)

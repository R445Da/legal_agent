"""
The entry-building pipeline: a resumable state machine with human gates.

The old archive flow was one black-box call — `extract_entry` → one "accept or
discard" ticket → `commit_entry`. This turns it into six named steps, each
persisted (`app/rag/runs.py`) so a reload or a backend failure never loses a
step or the raw text:

    classify → extract → timeline → similar → labels → commit

How often it stops for you is the **run mode** (`WorkflowState.mode`):

    "review" (default) — runs everything, stops once at a single review panel
                         that only asks about fields that came back empty
    "steps"            — stops at every gate (extract, timeline, similar, labels)
    "auto"             — stops for nothing; extract → derive → commit

`classify` no longer calls the LLM (the router already ran upstream), and the
`similar` tool loop is off unless `SIMILAR_TOOL_BUDGET_S` is set — so a common
`review` run is one LLM call (`extract`) plus one pause.

Deliberately dependency-free and LangGraph-shaped, so it can be swapped later:

    WorkflowState      → the graph state (a plain serialisable dataclass)
    Step.run           → a node: (state) -> a partial state update
    Step.gate          → interrupt(): pause, persist, resume with the user's value
    advance(user_patch)→ Command(resume=user_patch)
    Run / RunStep rows → the checkpointer

Every LLM-driven step has a deterministic fallback, so "don't stop until the
entry is made" holds even when a small local model fumbles JSON or a tool call.
"""

import asyncio
import os
import time
from dataclasses import asdict, dataclass, field, fields
from typing import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.base import LLMProvider
from app.rag import runs
from app.rag.orchestrator import _INTENT_FA

# Step ids, in order. Kept as a constant so the UI and the console agree.
STEP_IDS = ("classify", "extract", "timeline", "similar", "labels", "commit")

_STATUS_TERMINAL = {"done", "skipped"}


# --------------------------------------------------------------------------- #
# State
# --------------------------------------------------------------------------- #
# How much the run pauses for you:
#   "review" (default) — run everything, stop once for a single review + commit,
#                        and only ask about fields that came back empty
#   "steps"            — stop at every gate (extract, timeline, similar, labels)
#   "auto"             — stop for nothing; extract, derive, commit straight through
RUN_MODES = ("review", "steps", "auto")
_MODE_FA = {"review": "تأیید یک‌باره", "steps": "گام‌به‌گام", "auto": "خودکار"}

# Fields a finished entry really should have. The review gate turns any that are
# still empty into a small "fill these in" form instead of making you re-check
# everything.
REQUIRED_FIELDS = (
    ("title", "عنوان"),
    ("summary", "خلاصه"),
    ("entities.case_number", "شمارهٔ پرونده"),
)


@dataclass
class WorkflowState:
    raw_text: str = ""
    source: str = ""
    mode: str = "review"                             # review | steps | auto
    route: dict = field(default_factory=dict)        # {intent, confidence, reason, clarification}
    draft: dict = field(default_factory=dict)        # extract_entry() output, edited at its gate
    timeline: list = field(default_factory=list)     # [{date, title, detail, source}]
    similar: list = field(default_factory=list)      # [{entry_id, document_id, title, score, outcome, keep}]
    labels: list = field(default_factory=list)       # [str]
    related: list = field(default_factory=list)      # the kept subset of `similar`, written onto the Entry
    tool_log: list = field(default_factory=list)     # [{tool, args, summary}] from the similar-step agent
    step_status: dict = field(default_factory=dict)  # {step_id: pending|running|done|failed|awaiting_input}
    entry_id: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> "WorkflowState":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (data or {}).items() if k in known})

    def status_of(self, step_id: str) -> str:
        return self.step_status.get(step_id, "pending")


@dataclass
class StepResult:
    patch: dict                      # merged into the state
    detail: str = ""                 # one human-readable line for the log
    status: str = "done"             # done | skipped | failed


@dataclass
class Step:
    id: str
    label: str                       # Persian, shown in the console and the chat
    gate: bool                       # pause for the user after this step
    run: Callable[["WorkflowState", LLMProvider, AsyncSession], Awaitable[StepResult]]


# --------------------------------------------------------------------------- #
# The steps
# --------------------------------------------------------------------------- #
async def _classify(state: WorkflowState, llm: LLMProvider, session: AsyncSession) -> StepResult:
    """No LLM call.

    The router already ran upstream (`agent._answer_pending` / `run_assistant`)
    and picked `archive`, or you forced it with the «نوع پیام» selector. Running
    the classifier a second time here was pure latency — and a small local model
    would sometimes contradict itself with «نامشخص». So this step just records
    the decision that already happened.
    """
    forced = (state.route or {}).get("forced_intent")
    return StepResult(
        {"route": {"intent": "archive", "confidence": 1.0,
                   "source": "دستی" if forced else "مسیریاب"}},
        detail="ثبت مطلب جدید" + ("" if forced else " — از تشخیص مسیریاب"),
    )


async def _extract(state: WorkflowState, llm: LLMProvider, session: AsyncSession) -> StepResult:
    from app.rag.orchestrator import extract_entry

    draft = await extract_entry(llm, state.raw_text)
    have = [name for key, name in (("title", "عنوان"), ("summary", "خلاصه")) if draft.get(key)]
    ent = draft.get("entities") or {}
    if ent.get("case_number"):
        have.append("شمارهٔ پرونده")
    detail = "استخراج شد: " + "، ".join(
        have + [f"{len(draft.get('parties', []))} طرف", f"{len(draft.get('events', []))} رویداد"]
    )
    return StepResult({"draft": draft}, detail=detail)


async def _timeline(state: WorkflowState, llm: LLMProvider, session: AsyncSession) -> StepResult:
    """Turn the extracted events into ordered timeline rows the user can edit."""
    rows: list[dict] = []
    for event in state.draft.get("events") or []:
        if isinstance(event, dict):
            title = (
                event.get("description") or event.get("what")
                or event.get("type") or event.get("detail") or ""
            )
            detail = event.get("detail", "") if title != event.get("detail") else ""
            rows.append({
                "date": str(event.get("date") or ""), "title": str(title),
                "detail": str(detail or ""), "source": "استخراج",
            })
        elif str(event).strip():
            rows.append({"date": "", "title": str(event).strip(), "detail": "", "source": "استخراج"})
    rows.sort(key=lambda r: r["date"] or "￿")
    return StepResult({"timeline": rows}, detail=f"{len(rows)} رویداد روی خط زمان")


_SIMILAR_SYSTEM = (
    "You help a Persian legal archivist find prior records related to a new "
    "case. Call `search_entries` a few times with different angles — the "
    "parties' names, the charge/topic, the court — and `find_related` on a "
    "short description. Then briefly say which prior records look most related "
    "and why. Reply in Persian."
)


async def _similar(state: WorkflowState, llm: LLMProvider, session: AsyncSession) -> StepResult:
    """Find related records.

    The similar list itself is built deterministically from several query facets
    (robust on a small local model). A bounded tool loop runs alongside it — the
    model tries its own angles and the trail is shown so the user watches the
    agent work — but the loop's prose is not trusted for the list, so a fumbled
    tool call never breaks the step.
    """
    from app.rag.catalog import search_entries
    from app.rag.orchestrator import find_related

    draft = state.draft or {}
    own_title = (draft.get("title") or "").strip()
    query = _draft_query(draft, state.raw_text)

    # One lexical pass — `search_entries` already weights rare terms, so the
    # combined query (title + topic + case number + party names) is enough. The
    # old per-facet loop fired dozens of document-frequency count queries and
    # cost ~12 s for no better result.
    similar: list[dict] = []
    seen_docs: set[str] = set()
    for entry in await search_entries(session, query, limit=8):
        if own_title and (entry.title or "").strip() == own_title:
            continue  # a re-run of the same source matching its earlier self
        did = str(entry.document_id) if entry.document_id else None
        if did:
            seen_docs.add(did)
        similar.append({
            "entry_id": str(entry.id), "document_id": did,
            "title": entry.title or "بدون عنوان",
            "score": None, "outcome": _outcome_of(entry), "keep": True,
            "why": "واژهٔ مشترک با متن",
        })

    # Only fall back to semantic search (embed + rerank, ~5 s) when lexical
    # found little.
    if len(similar) < 4:
        for doc in await find_related(
            session, query, exclude_source=state.source, top_k=4,
        ):
            if doc["document_id"] in seen_docs:
                continue
            seen_docs.add(doc["document_id"])
            similar.append({
                "entry_id": None, "document_id": doc["document_id"], "title": doc["title"],
                "score": doc.get("similarity"), "outcome": "", "keep": True,
                "why": "شباهت معنایی",
            })

    # The deterministic list above is the result. The tool loop below is only a
    # *visible trail* of the model trying its own search angles — it is off by
    # default because it adds 10-40 s on a local model for no change to the
    # output. Turn it on with `SIMILAR_TOOL_BUDGET_S=45` (a wall-clock budget).
    tool_log: list[dict] = []
    budget = float(os.environ.get("SIMILAR_TOOL_BUDGET_S", "0"))
    if budget > 0:
        try:
            from app.rag.tools import run_with_tools

            loop = await asyncio.wait_for(
                run_with_tools(
                    llm, session,
                    prompt=f"پرونده جدید:\n{(state.raw_text or '')[:1200]}",
                    system=_SIMILAR_SYSTEM, max_rounds=2, max_tokens=400,
                ),
                timeout=budget,
            )
            tool_log = loop.tool_log
        except Exception:  # noqa: BLE001 — TimeoutError included; the trail is optional
            tool_log = []

    detail = f"{len(similar)} مورد مشابه"
    if tool_log:
        detail += f" · {len(tool_log)} فراخوانی ابزار"
    return StepResult({"similar": similar, "tool_log": tool_log}, detail=detail)


async def _labels(state: WorkflowState, llm: LLMProvider, session: AsyncSession) -> StepResult:
    """No LLM call by default.

    The extractor already returns `tags`; those plus a keyword match of the
    record against the seed taxonomy and the corpus's existing tags gives a
    solid starting set that the user edits at the gate. `LABELS_LLM=1` turns on
    the extra model call for a smarter proposal (adds ~10-25 s on a local model).
    """
    from app.rag.taxonomy import _clean, corpus_tags, leaves, propose_labels, roots

    vocab = list(dict.fromkeys([*leaves(), *roots(), *(await corpus_tags(session))]))
    existing = _clean([str(t) for t in (state.draft.get("tags") or [])], vocab)

    entities = state.draft.get("entities") or {}
    text = " ".join(str(x) for x in (
        state.draft.get("title"), state.draft.get("summary"),
        entities.get("topic"), entities.get("court"),
    ) if x)
    keyword = [term for term in vocab if term and term in text]

    labels = list(dict.fromkeys([*existing, *keyword]))[:6]

    if not labels and os.environ.get("LABELS_LLM") == "1":
        labels = (await propose_labels(llm, state.draft, session))[:6]

    return StepResult({"labels": labels}, detail=f"{len(labels)} برچسب: {'، '.join(labels) or '—'}")


async def _commit(state: WorkflowState, llm: LLMProvider, session: AsyncSession) -> StepResult:
    from app.rag.orchestrator import commit_entry

    draft = dict(state.draft)
    draft["tags"] = list(state.labels)
    if state.timeline:
        # The approved timeline is the source of truth for events on commit.
        draft["events"] = [
            {"date": row.get("date", ""), "description": row.get("title", "")}
            for row in state.timeline if row.get("title")
        ]
    kept = [s for s in state.similar if s.get("keep")]
    entry = await commit_entry(
        session, draft, state.raw_text, source=state.source, related=kept,
    )
    await session.commit()
    return StepResult(
        {"entry_id": str(entry.id), "related": kept},
        detail=f"مدخل ثبت شد — شناسه {entry.id}",
    )


STEPS: list[Step] = [
    Step("classify", "تشخیص نوع", gate=False, run=_classify),
    Step("extract", "استخراج ساختاریافته", gate=True, run=_extract),
    Step("timeline", "خط زمان", gate=True, run=_timeline),
    Step("similar", "پرونده‌های مشابه", gate=True, run=_similar),
    Step("labels", "برچسب‌ها", gate=True, run=_labels),
    Step("commit", "ثبت در آرشیو", gate=False, run=_commit),
]
_BY_ID = {s.id: s for s in STEPS}


# --------------------------------------------------------------------------- #
# The driver
# --------------------------------------------------------------------------- #
async def start(
    session: AsyncSession, *, raw_text: str, source: str, llm: LLMProvider,
    mode: str = "review", forced_intent: str | None = None,
) -> dict:
    """Create the run and execute up to the first pause (or to commit, in
    `auto` mode)."""
    state = WorkflowState(
        raw_text=raw_text, source=source,
        mode=mode if mode in RUN_MODES else "review",
        route={"forced_intent": forced_intent} if forced_intent else {},
    )
    run = await runs.create_run(
        session, raw_text=raw_text, source=source, state=state.to_dict(),
    )
    return await advance(session, str(run.id), llm)


def _missing_required(state: WorkflowState) -> list[tuple[str, str]]:
    """Required fields that came back empty — the review gate asks about these."""
    out = []
    for path, fa in REQUIRED_FIELDS:
        if path.startswith("entities."):
            value = (state.draft.get("entities") or {}).get(path.split(".", 1)[1])
        else:
            value = state.draft.get(path)
        if not (value and str(value).strip()):
            out.append((path, fa))
    return out


def _pauses_here(step: Step, state: WorkflowState) -> bool:
    """Whether the run stops for the user after `step`, given the run mode."""
    if state.mode == "auto":
        return False
    if state.mode == "steps":
        return step.gate
    # "review": one stop, at `labels` (the last step before commit), where the
    # whole record is shown at once.
    return step.id == "labels"


async def advance(
    session: AsyncSession, run_id: str, llm: LLMProvider, *, user_patch: dict | None = None,
) -> dict:
    """Run the pipeline forward from where it stopped.

    `user_patch` carries a gate's edits (e.g. `{"draft": {...}}`). With it the
    awaiting step is marked done and the run continues; without it a failed step
    is retried and a still-awaiting run is returned unchanged.
    """
    view = await runs.load_run(session, run_id)
    if view is None:
        raise ValueError(f"run {run_id} not found")
    state = WorkflowState.from_dict(view["state"])
    state.raw_text = view["raw_text"]
    state.source = view["source"] or state.source

    if user_patch is not None:
        awaiting = next(
            (s for s in STEPS if state.status_of(s.id) == "awaiting_input"), None
        )
        if awaiting is not None:
            for key, value in user_patch.items():
                if key in {f.name for f in fields(WorkflowState)}:
                    setattr(state, key, value)
            state.step_status[awaiting.id] = "done"
            await runs.record_step(
                session, run_id, seq=STEP_IDS.index(awaiting.id) + 1,
                step_id=awaiting.id, label=awaiting.label, status="done",
                detail="ویرایش شما اعمال شد", payload=_payload(awaiting.id, state),
            )
            await runs.save_state(session, run_id, state.to_dict())

    for index, step in enumerate(STEPS):
        current = state.status_of(step.id)
        if current in _STATUS_TERMINAL:
            continue
        if current == "awaiting_input":
            return await runs.load_run(session, run_id)  # still waiting on the user

        state.step_status[step.id] = "running"
        await runs.record_step(
            session, run_id, seq=index + 1, step_id=step.id, label=step.label,
            status="running",
        )
        t0 = time.perf_counter()
        try:
            result = await step.run(state, llm, session)
        except Exception as error:  # noqa: BLE001 — surfaced to the user for retry
            state.step_status[step.id] = "failed"
            await runs.record_step(
                session, run_id, seq=index + 1, step_id=step.id, label=step.label,
                status="failed", error=f"{type(error).__name__}: {error}",
                ms=round((time.perf_counter() - t0) * 1000),
            )
            await runs.save_state(session, run_id, state.to_dict(), status="failed")
            return await runs.load_run(session, run_id)

        ms = round((time.perf_counter() - t0) * 1000)
        for key, value in result.patch.items():
            setattr(state, key, value)

        if result.status != "skipped" and _pauses_here(step, state):
            state.step_status[step.id] = "awaiting_input"
            await runs.record_step(
                session, run_id, seq=index + 1, step_id=step.id, label=step.label,
                status="awaiting_input", detail=result.detail,
                payload=_payload(step.id, state), ms=ms,
            )
            await runs.save_state(session, run_id, state.to_dict(), status="awaiting_input")
            return await runs.load_run(session, run_id)

        state.step_status[step.id] = result.status
        await runs.record_step(
            session, run_id, seq=index + 1, step_id=step.id, label=step.label,
            status=result.status, detail=result.detail,
            payload=_payload(step.id, state), ms=ms,
        )

    await runs.save_state(session, run_id, state.to_dict(), status="committed")
    await runs.set_status(session, run_id, "committed", entry_id=state.entry_id)
    return await runs.load_run(session, run_id)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _payload(step_id: str, state: WorkflowState) -> dict:
    if step_id == "labels":
        # In "review" mode this gate shows the whole record at once, so its
        # payload carries everything the review panel needs.
        base = {"labels": state.labels}
        if state.mode == "review":
            base.update({
                "mode": "review",
                "draft": state.draft,
                "timeline": state.timeline,
                "similar": state.similar,
                "missing": _missing_required(state),
            })
        return base
    return {
        "classify": state.route,
        "extract": state.draft,
        "timeline": {"rows": state.timeline},
        "similar": {"items": state.similar, "tool_log": state.tool_log},
        "commit": {"entry_id": state.entry_id, "related": state.related},
    }.get(step_id, {})


def _draft_query(draft: dict, raw_text: str) -> str:
    """A short query that captures what the record is about, for the similar step."""
    ent = draft.get("entities") or {}
    bits = [
        draft.get("title") or "",
        ent.get("topic") or "",
        ent.get("case_number") or "",
        " ".join(str(p.get("name", "")) for p in (draft.get("parties") or []) if isinstance(p, dict)),
    ]
    query = " ".join(b for b in bits if b).strip()
    return query or (raw_text or "")[:400]


def _outcome_of(entry) -> str:
    """Best-effort past outcome of a matched entry, for «نتیجه» in the similar list."""
    ent = entry.entities or {}
    if ent.get("status"):
        return str(ent["status"])
    summary = (entry.summary or "").strip()
    if summary:
        first = summary.split(". ")[0].split("۔")[0]
        return first[:80] + ("…" if len(first) > 80 else "")
    return ""

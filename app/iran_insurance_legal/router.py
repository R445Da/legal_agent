from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.llm import registry
from app.demo.stages import STAGES
from app.rag import (agenda, casebase, catalog, ci, conversations, hooks, lawbase, rerank, runs, voice,
                     workflow)
from app.rag import transcribe as stt
from app.rag.cases import all_events, derive_cases, tag_counts
from app.rag.catalog import search_entries
from app.rag.orchestrator import _INTENT_FA, CASE_TYPES, INSURANCE_LINES, route
from app.rag.evaluate import load_cases, run_eval
from app.rag.pipeline import answer_question
from app.rag.retriever import effective_config, retrieve_scored
from app.rag.taxonomy import TAXONOMY, leaves
from app.rag.textnorm import normalize_fa

router = APIRouter(prefix="/legal/api", tags=["iran-insurance-legal"])

DIST = Path(__file__).resolve().parents[2] / "iran-insurance-legal" / "dist"


def _sessions():
    # Imported lazily: app.main includes this router at the bottom of its module.
    from app.main import SessionLocal

    return SessionLocal


def _llm(request: Request, model: str | None):
    """The default provider, or a per-request one by registry id — as in app.main."""
    if not model or model == getattr(request.app.state, "model_id", None):
        return request.app.state.llm
    return registry.resolve(model)


def _require(llm):
    if not llm.is_available():
        raise HTTPException(503, f"LLM provider '{llm.name}' is not available")
    return llm


def _number_key(value) -> str:
    return normalize_fa(str(value or "")).strip()


@router.get("/state")
async def state():
    """Everything the case-oriented views read, in one call — the same bundle
    `app/ui/data.py` builds for Streamlit, including each derived case's
    relational `record` (its `legal_cases` row)."""
    async with _sessions()() as s:
        entries = await catalog.list_entries(s)
        bundle = {
            "entries": entries,
            "counts": await catalog.counts(s),
            "collections": (await catalog.collections(s))["collections"],
            "facets": await catalog.facets(s),
            "schema": await catalog.schema_overview(s),
            "legal_cases": await casebase.list_cases(s),
            "law_titles": await lawbase.law_titles(s),
            "archive": await casebase.archive_stats(s),
        }
    cases = derive_cases(entries)
    by_number = {_number_key(r["case_number"]): r for r in bundle["legal_cases"]}
    for case in cases:
        case["record"] = by_number.get(_number_key(case["number"])) if case["number"] else None
    bundle.update({
        "cases": cases,
        "events": all_events(cases),
        "tags": tag_counts(cases),
        "review_queue": [c for c in cases if c["incomplete"]],
        "taxonomy": TAXONOMY,
    })
    return bundle


@router.get("/options")
async def options():
    """The vocabularies and choices the UI renders as controls."""
    return {
        "intents": _INTENT_FA,
        "run_modes": [{"id": m, "label": workflow._MODE_FA.get(m, m)} for m in workflow.RUN_MODES],
        "steps": [{"id": s.id, "label": s.label, "gate": s.gate} for s in workflow.STEPS],
        "case_types": CASE_TYPES,
        "insurance_lines": INSURANCE_LINES,
        "taxonomy_leaves": leaves(),
        "retrieval": effective_config(),
        "rerank": {"enabled": rerank.enabled(), "default": rerank.default_model(),
                   "choices": [{"id": m, "label": label} for m, label in rerank.CHOICES]},
        "stt": {"enabled": stt.enabled(), "default": stt.default_choice() if stt.enabled() else None,
                "choices": [{"id": c, "label": label} for c, label in (stt.choices() if stt.enabled() else [])]},
    }


class RouteRequest(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    model: str | None = None


@router.post("/route")
async def route_only(req: RouteRequest, request: Request):
    """Classify a message without acting on it. The browser then calls the
    matching executor — so nothing is drafted from a mis-routed question.
    The session lets a party the archive knows decide the route, as it does
    in `run_assistant`."""
    llm = _require(_llm(request, req.model))
    async with _sessions()() as s:
        decision = await route(llm, req.text, session=s)
    return {"intent": decision.intent, "confidence": decision.confidence,
            "clarification": decision.clarification, "reason": decision.reason,
            "label": _INTENT_FA.get(decision.intent, decision.intent)}


@router.post("/command")
async def command(req: RouteRequest):
    """Whether a whole (spoken) utterance is a session command — «گفتگوی جدید»,
    «پروندهٔ جدید», «توقف» — rather than a message (`app/rag/voice.py`)."""
    return {"command": voice.command_of(req.text)}


class Retrieval(BaseModel):
    document_ids: list[str] | None = None  # «پرسش از این پرونده»: only this case's documents
    hybrid: bool | None = None
    rerank: bool | None = None
    candidates: int | None = Field(default=None, ge=1, le=200)
    rerank_top: int | None = Field(default=None, ge=1, le=100)
    rerank_model: str | None = None


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=8000)
    top_k: int = Field(default=5, ge=1, le=20)
    model: str | None = None
    collection: str | None = None
    filters: dict | None = None
    retrieval: Retrieval = Field(default_factory=Retrieval)
    knobs: dict = Field(default_factory=dict)
    max_tokens: int = Field(default=1024, ge=64, le=16000)


@router.post("/ask")
async def ask(req: AskRequest, request: Request):
    """A grounded answer with every control from the Streamlit left panel:
    retrieval overrides and the selected model's knobs."""
    llm = _require(_llm(request, req.model))
    async with _sessions()() as s:
        res = await answer_question(
            s, llm, req.question, top_k=req.top_k, collection=req.collection, filters=req.filters,
            retrieval=req.retrieval.model_dump(exclude_none=True), max_tokens=req.max_tokens, **req.knobs,
        )
    return {"answer": res.answer, "contexts": res.contexts, "model": res.model, "latency_ms": res.latency_ms,
            "steps": res.steps, "retrieval": res.retrieval, "input_tokens": res.input_tokens,
            "output_tokens": res.output_tokens}


class RetrieveRequest(BaseModel):
    query: str = Field(min_length=1, max_length=8000)
    top_k: int = Field(default=5, ge=1, le=50)
    collection: str | None = None
    filters: dict | None = None
    retrieval: Retrieval = Field(default_factory=Retrieval)
    with_entries: bool = True


@router.post("/retrieve")
async def retrieve(req: RetrieveRequest):
    """Retrieval only — the retrieval lab and the labeling screen. Returns the
    hits, the structured entries matched on rare terms, and per-stage ms."""
    trace: dict = {}
    async with _sessions()() as s:
        rows = await retrieve_scored(
            s, req.query, top_k=req.top_k, collection=req.collection, filters=req.filters,
            trace=trace, **req.retrieval.model_dump(exclude_none=True),
        )
        hits = [
            {"n": i + 1, "chunk_id": str(c.id), "document_id": str(c.document_id),
             "title": c.document.title or c.document.source, "source": c.document.source,
             "chunk_index": c.chunk_index, "similarity": round(1 - d, 3), "text": c.text}
            for i, (c, d) in enumerate(rows)
        ]
        entries = []
        if req.with_entries:
            entries = [catalog.entry_dict(e) for e in await search_entries(s, req.query)]
    return {"query": req.query, "hits": hits, "entries": entries, "trace": trace,
            "config": {**effective_config(req.retrieval.hybrid, req.retrieval.rerank), "top_k": req.top_k}}


class AdvanceRequest(BaseModel):
    patch: dict | None = None
    model: str | None = None


@router.post("/runs/{run_id}/advance")
async def advance_run(run_id: str, req: AdvanceRequest, request: Request):
    """Resume a gated run. With `patch` the awaiting gate takes the user's
    edits and the run continues; without it a failed step is retried."""
    llm = _llm(request, req.model)
    async with _sessions()() as s:
        try:
            return await workflow.advance(s, run_id, llm, user_patch=req.patch)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc


@router.post("/runs/{run_id}/abandon")
async def abandon_run(run_id: str):
    async with _sessions()() as s:
        if await runs.get_run(s, run_id) is None:
            raise HTTPException(404, "no such run")
        await runs.set_status(s, run_id, "abandoned")
        return await runs.load_run(s, run_id)


# The chat thread as rows (`app/rag/conversations.py`). `/conversations` in
# app.main lists, reads and deletes threads; Streamlit starts them and appends
# turns in-process, so the browser needs these two to do the same.
class ConversationStart(BaseModel):
    title: str | None = Field(default=None, max_length=500)


@router.post("/conversations")
async def conversation_start(body: ConversationStart | None = None):
    async with _sessions()() as s:
        return await conversations.start(s, title=body.title if body else None, source="web")


# Keys `message_dict` owns; an `extra` carrying one would shadow the column
# (or collide with `add_message`'s own keyword arguments).
_TURN_RESERVED = frozenset({"id", "role", "text", "intent", "model", "created_at"})


class Turn(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    text: str = Field(default="", max_length=50_000)
    intent: str | None = None
    model: str | None = None
    extra: dict = Field(default_factory=dict)


@router.post("/conversations/{conversation_id}/messages")
async def conversation_turn(conversation_id: str, turn: Turn):
    """Append one turn. `extra` is what the turn rendered — the answer, the
    run, the pending edit — so reopening a thread shows what it showed."""
    extra = {k: v for k, v in turn.extra.items() if k not in _TURN_RESERVED}
    async with _sessions()() as s:
        message = await conversations.add_message(
            s, conversation_id, role=turn.role, text=turn.text,
            intent=turn.intent, model=turn.model, **extra,
        )
    if message is None:
        raise HTTPException(404, "گفتگو یافت نشد")
    return message


class Focus(BaseModel):
    kind: str = Field(pattern="^(entry|case|document|person|org)$")
    id: str = Field(min_length=1)
    label: str = ""


@router.put("/conversations/{conversation_id}/focus")
async def conversation_focus(conversation_id: str, focus: Focus):
    """Record the record this thread is working on — set after an edit is
    confirmed, as Streamlit's edit gate does."""
    async with _sessions()() as s:
        saved = await conversations.set_focus(s, conversation_id, kind=focus.kind, id=focus.id,
                                              label=focus.label)
    if saved is None:
        raise HTTPException(404, "گفتگو یافت نشد")
    return {"focus": saved}


class CaseEvent(BaseModel):
    date: str = ""
    title: str = Field(min_length=1, max_length=500)
    detail: str = ""
    reminder: bool = False


@router.post("/cases/{case_id}/events")
async def add_case_event(case_id: str, body: CaseEvent):
    """Put a dated item (or reminder) on a case's timeline — `agenda.add_event`,
    the same stream extracted events live in, so it shows in رویدادها too."""
    async with _sessions()() as s:
        event = await agenda.add_event(s, case_id, date=body.date, title=body.title,
                                       detail=body.detail, reminder=body.reminder)
    if event is None:
        raise HTTPException(404, "no entry holds this case")
    return event


@router.get("/integrations")
async def integrations():
    """Live CI runs and webhook delivery counts — the dashboard's CI panel."""
    from sqlalchemy import func, select

    from app.db.models import WebhookDelivery, WebhookSubscription

    async with _sessions()() as s:
        ci_runs = await ci.list_ci_runs(s, limit=5)
        subs = await s.scalar(select(func.count()).select_from(WebhookSubscription)) or 0
        rows = (await s.execute(select(WebhookDelivery.status, func.count()).group_by(WebhookDelivery.status))).all()
    return {"ci_runs": ci_runs, "hooks": {"subscriptions": subs, **{status: n for status, n in rows}}}


@router.post("/hooks/drain")
async def drain_hooks():
    """Send every due webhook delivery now instead of waiting for the worker."""
    return {"tried": await hooks.drain(_sessions())}


@router.get("/eval/files")
async def eval_files():
    return {"files": sorted(str(p) for p in Path("eval").glob("*.jsonl"))}


class EvalRequest(BaseModel):
    path: str = "eval/farsi.jsonl"
    top_k: int = Field(default=5, ge=1, le=20)
    collection: str | None = None
    retrieval: Retrieval = Field(default_factory=Retrieval)
    with_answers: bool = False
    model: str | None = None


@router.post("/eval")
async def evaluate(req: EvalRequest, request: Request):
    """Score the retriever with the retrieval panel's overrides — what the
    Streamlit eval screen and its reranker sweep run."""
    path = Path(req.path)
    if path.suffix != ".jsonl" or not path.resolve().is_relative_to(Path("eval").resolve()) or not path.exists():
        raise HTTPException(404, f"no eval file at {req.path}")
    llm = _require(_llm(request, req.model)) if req.with_answers else None
    async with _sessions()() as s:
        return await run_eval(s, load_cases(path), top_k=req.top_k, llm=llm, collection=req.collection,
                              retrieval=req.retrieval.model_dump(exclude_none=True))


@router.get("/demo/stages")
async def demo_stages():
    """The demo, as data (`app/demo/stages.py`) — the gallery lists it and the
    assistant offers it as chips on an empty conversation."""
    return {"stages": [asdict(stage) for stage in STAGES]}


@router.post("/transcribe")
async def transcribe_audio(file: UploadFile = File(...), choice: str | None = Query(default=None)):
    """Speech-to-text with the backend chosen in the settings panel."""
    if not stt.enabled():
        raise HTTPException(503, "speech-to-text is disabled (STT=0)")
    audio = await file.read()
    if not audio:
        raise HTTPException(400, "empty audio")
    try:
        return await stt.transcribe(audio, file.filename or "audio.webm", choice=choice)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"transcription failed: {exc}") from exc


def mount_spa(app: FastAPI) -> None:
    """Serve the built React app at /legal/ when its `dist/` exists."""
    if not (DIST / "index.html").exists():
        return

    @app.get("/legal", include_in_schema=False)
    async def _legal_slash():
        return RedirectResponse("/legal/")

    app.mount("/legal", StaticFiles(directory=DIST, html=True), name="iran-insurance-legal")

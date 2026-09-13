import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import (
    Body,
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.db.engine import create_schema, resolve_database_url
from app.db.models import AssistantAnswer, Chunk, Document, Entry, Label
from app.llm import registry
from app.llm.factory import get_llm_provider
from app.rag.bench import NothingIndexed, run_bench
from app.rag.ingest import get_document, ingest_document, list_documents
from app.rag.orchestrator import (
    ENTRY_SCHEMA,
    commit_entry,
    corpus_stats,
    extract_entry,
    find_related,
    run_assistant,
)
from app.rag.pipeline import answer_question
from app.rag.retriever import effective_config, retrieve_scored
from app.rag import (casebase, catalog, ci, conversation, conversations, entryedit, graph, hooks,
                     lawbase, vaultmap, vaultsync, workflow)
from app.rag import provenance as prov
from app.rag import runs as run_store
from app.rag import transcribe as stt

engine = create_async_engine(resolve_database_url())
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

STATIC_DIR = Path(__file__).parent / "static"


async def _drain_loop(interval: float = 3.0) -> None:
    """Send due webhook deliveries on a timer — including the ones the
    Streamlit process queued but could not send itself."""
    while True:
        try:
            await hooks.drain(SessionLocal)
        except Exception:  # noqa: BLE001 — keep the timer alive
            pass
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_schema(engine)
    app.state.llm = get_llm_provider()
    app.state.model_id = registry.default_id()
    app.state.drain_task = asyncio.create_task(_drain_loop())
    yield
    app.state.drain_task.cancel()
    await engine.dispose()


app = FastAPI(title="Legal RAG MVP", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def require_token(authorization: str | None = Header(default=None)):
    """No-op when API_TOKEN is unset; otherwise requires `Authorization: Bearer <token>`."""
    if not settings.api_token:
        return
    if authorization != f"Bearer {settings.api_token}":
        raise HTTPException(401, "Missing or invalid API token")


async def require_run_access(
    authorization: str | None = Header(default=None),
    token: str | None = Query(default=None),
):
    """Like `require_token`, but also accepts `?token=` — the build console is a
    browser page and `EventSource` cannot set an Authorization header."""
    if not settings.api_token:
        return
    if authorization == f"Bearer {settings.api_token}" or token == settings.api_token:
        return
    raise HTTPException(401, "Missing or invalid API token")


async def require_ci_token(authorization: str | None = Header(default=None)):
    """POST /ci/status: the CI_STATUS_TOKEN secret, or the API token."""
    accepted = {t for t in (os.environ.get("CI_STATUS_TOKEN"), settings.api_token) if t}
    if not accepted:
        return
    if authorization and authorization.startswith("Bearer ") and authorization[7:] in accepted:
        return
    raise HTTPException(401, "Missing or invalid CI token")


auth = [Depends(require_token)]
run_auth = [Depends(require_run_access)]
ci_auth = [Depends(require_ci_token)]


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #
class AskRequest(BaseModel):
    question: str
    top_k: int = Field(default=5, ge=1, le=20)
    model: str | None = None  # override the default LLM for this call
    collection: str | None = None  # scope retrieval to one document bucket
    filters: dict | None = None    # metadata filter: {year, group, case_number, ...}


def _llm(model: str | None):
    """The default provider, or a per-request one selected by registry id
    (e.g. "local::qwen2.5:3b", "openai::anthropic/claude-3-5-sonnet-20241022")."""
    if not model or model == getattr(app.state, "model_id", None):
        return app.state.llm
    return registry.resolve(model)


class Context(BaseModel):
    n: int
    document_id: str
    chunk_id: str | None = None
    title: str | None
    source: str
    chunk_index: int
    similarity: float
    text: str


class AskResponse(BaseModel):
    answer: str
    sources: list[str]
    model: str
    latency_ms: float | None
    contexts: list[Context] = []
    input_tokens: int | None = None
    output_tokens: int | None = None
    steps: list[dict] = []  # pipeline trace: [{name, detail, ms}]
    provenance: dict | None = None  # evidence, citation check, usage (app/rag/provenance.py)
    answer_id: str | None = None


class SearchRequest(BaseModel):
    query: str
    top_k: int = Field(default=5, ge=1, le=20)
    # Per-call overrides for the retrieval lab. None = use the server default.
    hybrid: bool | None = None
    rerank: bool | None = None
    # Scope retrieval to one body of material: samples | rulings | cases-en |
    # uploads. None searches everything.
    collection: str | None = None
    filters: dict | None = None    # {year, group, case_number, branch, doc_kind}


class SearchResponse(BaseModel):
    query: str
    hits: list[Context]
    config: dict = {}


class IngestItem(BaseModel):
    text: str
    source: str
    title: str | None = None
    metadata: dict = {}


class IngestRequest(BaseModel):
    documents: list[IngestItem]
    replace: bool = False
    # After indexing, also run structured extraction (parties / events /
    # entities -> an Entry row) for each new document, in the background.
    extract: bool = True


class IngestResult(BaseModel):
    source: str
    status: str
    chunks: int = 0


class IngestResponse(BaseModel):
    results: list[IngestResult]
    indexed_chunks: int


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/console", include_in_schema=False)
async def console():
    """The case-intelligence UI (sidebar shell, assistant chat, semantic
    search) — served alongside the developer index at /."""
    return FileResponse(STATIC_DIR / "console.html")


@app.get("/app", include_in_schema=False)
async def app_ui():
    """The Persian case-archive UI. `index.html` stays as the developer/lab
    surface (Ask / Search / Eval / Bench / model switcher)."""
    return FileResponse(STATIC_DIR / "app.html")


@app.get("/health")
async def health():
    async with SessionLocal() as session:
        chunk_count = await session.scalar(select(func.count()).select_from(Chunk))
        doc_count = await session.scalar(select(func.count()).select_from(Document))
    llm = app.state.llm
    return {
        "status": "ok",
        "llm_provider": llm.name,
        "llm_model": getattr(llm, "model", None),
        "llm_available": llm.is_available(),
        "indexed_documents": doc_count,
        "indexed_chunks": chunk_count,
        "auth_required": bool(settings.api_token),
        "embedding_model": settings.embedding_model,
        "stt_available": stt.enabled(),
    }


@app.get("/conversations", dependencies=auth)
async def conversations_list(limit: int = 30):
    """Chat threads, newest activity first, each with its message count and
    the record it was working on."""
    async with SessionLocal() as session:
        return {"conversations": await conversations.recent(session, limit=limit)}


@app.get("/conversations/{conversation_id}", dependencies=auth)
async def conversations_get(conversation_id: str):
    async with SessionLocal() as session:
        convo = await conversations.get(session, conversation_id)
    if convo is None:
        raise HTTPException(status_code=404, detail="گفتگو یافت نشد")
    return convo


@app.delete("/conversations/{conversation_id}", dependencies=auth)
async def conversations_delete(conversation_id: str):
    """Delete a thread and its turns. The answers it produced stay in
    `assistant_answers` — a chat list is the user's, the provenance is the
    archive's."""
    async with SessionLocal() as session:
        removed = await conversations.remove(session, conversation_id)
    if not removed:
        raise HTTPException(status_code=404, detail="گفتگو یافت نشد")
    return {"deleted": conversation_id}


@app.post("/entries/{entry_id}/propose", dependencies=auth)
async def entries_propose(entry_id: str, body: dict = Body(...)):
    """Build an edit proposal. **Writes nothing** — it returns the current
    value beside the new one for a human to confirm, and `/entries/{id}/apply`
    is the only thing that commits it.

    `{"field": "شمارهٔ پرونده", "value": "۱۴۰۰۲۲۲"}` replaces a field;
    `{"field": "رویدادها", "item": "۱۴۰۳/۰۵/۱۲ جلسهٔ کارشناسی"}` appends to a
    list field, keeping what is already there.
    """
    async with SessionLocal() as session:
        try:
            if "item" in body:
                proposal = await entryedit.propose_append(
                    session, entry_id, body.get("field", ""), body["item"])
            else:
                proposal = await entryedit.propose_edit(
                    session, entry_id, body.get("field", ""), body.get("value"))
        except entryedit.EditError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
    return {"proposal": proposal}


@app.post("/entries/{entry_id}/apply", dependencies=auth)
async def entries_apply(entry_id: str, body: dict = Body(...)):
    """Commit a proposal returned by `/entries/{id}/propose`."""
    proposal = body.get("proposal") or body
    if str(proposal.get("entry_id")) != str(entry_id):
        raise HTTPException(status_code=400, detail="پیشنهاد به این مدخل تعلق ندارد")
    async with SessionLocal() as session:
        try:
            saved = await entryedit.apply(session, proposal)
        except entryedit.EditError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
    if saved is None:
        raise HTTPException(status_code=404, detail="مدخل یافت نشد")
    return {"entry": saved}


@app.get("/graph/vault", dependencies=auth)
async def graph_vault():
    """The archive graph as JSON: the notes under `آرشیو/` and the wikilinks
    between them.

    Section ۲۰ of the Streamlit app renders exactly this payload, and it is a
    route rather than a view-local helper so any other frontend can draw the
    same graph without importing Streamlit. `nodes` carry a `uri` that opens
    the note in Obsidian.

    An empty `nodes` list means the vault has not been exported yet — run
    `python -m scripts.export_vault`; it is not an error.
    """
    data = vaultmap.load()
    return {
        "nodes": data["nodes"],
        "edges": data["edges"],
        "tags": data["tags"],
        "vault": data["vault"],
        "exported": bool(data["nodes"]),
    }


@app.post("/graph/vault/export", dependencies=auth)
async def graph_vault_export():
    """Write the database into the vault as notes. Writes only inside `آرشیو/`."""
    async with SessionLocal() as session:
        return await vaultsync.export_all(session)


@app.post("/transcribe", dependencies=auth)
async def transcribe_audio(file: UploadFile = File(...)):
    """Speech-to-text (local faster-whisper). The mic button posts recorded
    audio here; the returned text goes into the assistant composer."""
    if not stt.enabled():
        raise HTTPException(503, "speech-to-text is disabled (STT=0 in .env)")
    audio = await file.read()
    if not audio:
        raise HTTPException(400, "empty audio")
    try:
        return await stt.transcribe(audio, file.filename or "audio.webm")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"transcription failed: {exc}") from exc


# --------------------------------------------------------------------------- #
# Labels — human judgments that feed retrieval evaluation & tuning
# --------------------------------------------------------------------------- #
class LabelRequest(BaseModel):
    kind: str = Field(pattern="^(relevance|tag|review)$")
    target_type: str = Field(pattern="^(chunk|document|entry)$")
    target_id: str
    value: str | None = None            # "1"/"0" for relevance, tag name, verdict
    query: str | None = None            # the search/ask query, for relevance labels
    note: str | None = None
    labeled_by: str | None = None


@app.post("/labels", dependencies=auth)
async def add_label(req: LabelRequest):
    """Record a judgment. For relevance/review labels the (kind, target, query)
    triple is unique — re-posting updates the value so 👍/👎 can toggle."""
    async with SessionLocal() as session:
        existing = None
        if req.kind in ("relevance", "review"):
            existing = await session.scalar(
                select(Label).where(
                    Label.kind == req.kind,
                    Label.target_type == req.target_type,
                    Label.target_id == req.target_id,
                    Label.query == req.query,
                )
            )
        if existing:
            existing.value = req.value
            existing.note = req.note or existing.note
            lab = existing
        else:
            lab = Label(**req.model_dump())
            session.add(lab)
        await session.commit()
        await session.refresh(lab)
        return {"id": str(lab.id), "kind": lab.kind, "value": lab.value}


@app.get("/labels", dependencies=auth)
async def list_labels(
    kind: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    limit: int = Query(default=200, le=2000),
):
    async with SessionLocal() as session:
        q = select(Label).order_by(Label.created_at.desc()).limit(limit)
        if kind:
            q = q.where(Label.kind == kind)
        if target_type:
            q = q.where(Label.target_type == target_type)
        if target_id:
            q = q.where(Label.target_id == target_id)
        rows = (await session.execute(q)).scalars().all()
    return [
        {
            "id": str(r.id), "kind": r.kind, "target_type": r.target_type,
            "target_id": r.target_id, "value": r.value, "query": r.query,
            "note": r.note, "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@app.delete("/labels/{label_id}", dependencies=auth)
async def delete_label(label_id: str):
    async with SessionLocal() as session:
        lab = await session.get(Label, label_id)
        if lab is None:
            raise HTTPException(404, "no such label")
        await session.delete(lab)
        await session.commit()
    return {"deleted": label_id}


@app.get("/labels/summary", dependencies=auth)
async def labels_summary():
    """Coverage numbers so the UI can show how much labeled data exists and how
    ready it is to drive an eval run."""
    async with SessionLocal() as session:
        by_kind = dict(
            (await session.execute(
                select(Label.kind, func.count()).group_by(Label.kind)
            )).all()
        )
        rel = (await session.execute(
            select(Label.query, Label.value).where(Label.kind == "relevance")
        )).all()
        queries = {}
        for qtext, val in rel:
            b = queries.setdefault(qtext or "", {"pos": 0, "neg": 0})
            b["pos" if val == "1" else "neg"] += 1
        usable = [q for q, b in queries.items() if b["pos"]]
        docs_tagged = await session.scalar(
            select(func.count(func.distinct(Label.target_id))).where(Label.kind == "tag")
        )
    return {
        "by_kind": {k: v for k, v in by_kind.items()},
        "relevance_queries": len(queries),
        "eval_ready_queries": len(usable),  # queries with ≥1 positive judgment
        "documents_tagged": docs_tagged or 0,
    }


@app.get("/models", dependencies=auth)
async def models():
    """Every model the showcase can switch to on the fly: local (Ollama)
    plus cloud (the 9router gateway, and direct Anthropic if keyed). Each
    entry carries an opaque `id` to pass back as the `model` field."""
    return {
        "current": getattr(app.state, "model_id", registry.default_id()),
        "models": registry.catalog(),
    }


@app.post("/ask", response_model=AskResponse, dependencies=auth)
async def ask(req: AskRequest):
    llm = _llm(req.model)
    if not llm.is_available():
        raise HTTPException(
            503,
            f"LLM provider '{llm.name}' is not available "
            "(missing API key or unreachable endpoint).",
        )
    async with SessionLocal() as session:
        if not await session.scalar(select(func.count()).select_from(Chunk)):
            raise HTTPException(409, "No documents indexed yet.")
        result = await answer_question(
            session, llm, req.question, top_k=req.top_k,
            collection=req.collection, filters=req.filters,
        )
        evidence = prov.evidence_from_contexts(result.contexts)
        block = prov.build_provenance(
            intent="query", provider=llm.name, model=result.model, evidence=evidence,
            usage={"calls": 1, "input_tokens": result.input_tokens or 0,
                   "output_tokens": result.output_tokens or 0},
            answer=result.answer, latency_ms=result.latency_ms,
        )
        answer_id = await prov.persist_answer(
            session, intent="query", question=req.question, answer=result.answer,
            provenance=block, model=result.model,
        )
        return AskResponse(**result.__dict__, provenance=block, answer_id=answer_id)


@app.post("/search", response_model=SearchResponse, dependencies=auth)
async def search(req: SearchRequest):
    """Retrieval only — no LLM call. The fast way to inspect what the
    retrieval pipeline returns for a query. `hybrid` / `rerank` override the
    server defaults for this one call so the retrieval lab can A/B them."""
    async with SessionLocal() as session:
        scored = await retrieve_scored(
            session, req.query, top_k=req.top_k, hybrid=req.hybrid,
            rerank=req.rerank, collection=req.collection, filters=req.filters,
        )
        hits = [
            Context(
                n=i + 1,
                document_id=str(chunk.document_id),
                chunk_id=str(chunk.id),
                title=chunk.document.title or chunk.document.source,
                source=chunk.document.source,
                chunk_index=chunk.chunk_index,
                similarity=round(1.0 - distance, 3),
                text=chunk.text,
            )
            for i, (chunk, distance) in enumerate(scored)
        ]
    return SearchResponse(
        query=req.query,
        hits=hits,
        config={
            **effective_config(req.hybrid, req.rerank),
            "top_k": req.top_k,
            "collection": req.collection or "all",
        },
    )


@app.get("/schema", dependencies=auth)
async def schema():
    """What the system stores and how — so the UI can explain itself and drive a
    guided input form without the user knowing any data structures."""
    async with SessionLocal() as session:
        docs = await session.scalar(select(func.count()).select_from(Document))
        chunks = await session.scalar(select(func.count()).select_from(Chunk))
        entries = await session.scalar(select(func.count()).select_from(Entry))
        avg_chunks = round((chunks / docs), 1) if docs else 0
    return {
        "model": [
            {
                "name": "Document", "fa": "سند",
                "what": "یک سند/متن خام همان‌طور که وارد شده",
                "count": docs,
                "fields": ["source (کلید یکتا)", "title", "raw_text", "doc_metadata (شامل collection)", "created_at"],
            },
            {
                "name": "Chunk", "fa": "قطعه",
                "what": f"تکه‌های سند برای بازیابی؛ هر قطعه یک بردار تعبیه و یک نمایهٔ متنی دارد. میانگین {avg_chunks} قطعه در هر سند.",
                "count": chunks,
                "fields": [f"embedding (بردار {settings.embedding_model.split('/')[-1]})", "text (نرمال‌شده)", "text_search (tsvector)", "chunk_index"],
            },
            {
                "name": "Entry", "fa": "مدخل ساختاریافته",
                "what": "دادهٔ استخراج‌شده از یک جلسه/سند — همان چیزی که نمای «پرونده‌ها» از آن ساخته می‌شود",
                "count": entries,
                "fields": [f["label"] for f in ENTRY_SCHEMA["fields"]],
            },
        ],
        "entry_form": ENTRY_SCHEMA,
        "pipeline": {
            "query": ["نرمال‌سازی", "تعبیهٔ پرسش", "جستجوی برداری", "جستجوی متنی (BM25-وار)", "ترکیب RRF", "بازرتبه‌بندی", "تولید پاسخ"],
            "archive": ["تشخیص نوع", "استخراج ساختاریافته ✋", "خط زمان ✋", "پرونده‌های مشابه (ابزار) ✋", "برچسب‌ها ✋", "ثبت + نمایه‌سازی"],
            "analytics": ["تشخیص نوع", "تجمیع SQL", "خلاصهٔ زبانی"],
        },
        "pipeline_note": "✋ = توقف برای تأیید شما. هر اجرا در جدول runs ذخیره و در «کارگاه ساخت» (/runs/view) قابل مشاهده است.",
    }


@app.get("/facets", dependencies=auth)
async def facets():
    """Distinct metadata values (with counts) that retrieval can be filtered on —
    powers the filter dropdowns in the search / retrieval-lab UI."""
    keys = ("year", "group", "doc_kind", "branch", "status")
    out: dict = {}
    async with SessionLocal() as session:
        for key in keys:
            rows = (
                await session.execute(
                    select(
                        Document.doc_metadata[key].astext.label("v"),
                        func.count().label("n"),
                    )
                    .where(Document.doc_metadata[key].astext.isnot(None))
                    .group_by("v")
                    .order_by(func.count().desc())
                    .limit(40)
                )
            ).all()
            out[key] = [{"value": r.v, "documents": r.n} for r in rows if r.v]
    return out


@app.get("/collections", dependencies=auth)
async def collections():
    """The document buckets retrieval can be scoped to, with counts."""
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(
                    Document.doc_metadata["collection"].astext.label("name"),
                    func.count().label("documents"),
                ).group_by("name")
            )
        ).all()
    total = sum(r.documents for r in rows)
    return {
        "collections": [
            {"name": r.name or "uploads", "documents": r.documents} for r in rows
        ],
        "total_documents": total,
    }


async def _extract_documents(doc_ids: list[str]) -> None:
    """Background: give each freshly-ingested document its structured Entry
    (parties / representation / events / entities / tags), the same extraction
    the assistant's archive flow runs. Failures are logged, not raised — the
    document is already indexed and `scripts.extract` can backfill later."""
    if not doc_ids:
        return
    llm = get_llm_provider()
    async with SessionLocal() as session:
        for doc_id in doc_ids:
            doc = await session.get(Document, doc_id)
            if doc is None:
                continue
            already = await session.scalar(
                select(Entry.id).where(Entry.document_id == doc.id)
            )
            if already:
                continue
            try:
                draft = await extract_entry(llm, doc.raw_text)
                related = await find_related(
                    session, doc.raw_text, exclude_source=doc.source
                )
                session.add(
                    Entry(
                        document_id=doc.id,
                        kind=draft.get("kind", "session"),
                        title=draft.get("title") or doc.title,
                        summary=draft.get("summary", ""),
                        parties=draft.get("parties", []),
                        representation=draft.get("representation", []),
                        events=draft.get("events", []),
                        entities=draft.get("entities", {}),
                        tags=draft.get("tags", []),
                        related_ids=[r["document_id"] for r in related],
                        raw_text=doc.raw_text,
                    )
                )
                await session.commit()
            except Exception as exc:  # noqa: BLE001
                await session.rollback()
                print(f"[ingest] extraction failed for {doc.source}: {exc!r}", flush=True)


@app.post("/ingest", response_model=IngestResponse, dependencies=auth)
async def ingest(req: IngestRequest, background: BackgroundTasks):
    results: list[IngestResult] = []
    new_doc_ids: list[str] = []
    async with SessionLocal() as session:
        for item in req.documents:
            doc, status = await ingest_document(
                session,
                text=item.text,
                source=item.source,
                title=item.title,
                metadata=item.metadata,
                replace=req.replace,
            )
            if doc is not None and status in ("created", "replaced"):
                new_doc_ids.append(str(doc.id))
            results.append(
                IngestResult(
                    source=item.source,
                    status=status,
                    chunks=len(doc.chunks) if doc else 0,
                )
            )
        await session.commit()
        total = await session.scalar(select(func.count()).select_from(Chunk))

    if req.extract and new_doc_ids:
        background.add_task(_extract_documents, new_doc_ids)

    return IngestResponse(results=results, indexed_chunks=total)


@app.get("/documents", dependencies=auth)
async def documents(
    q: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    collection: str | None = None,
    year: str | None = None,
    group: str | None = None,
    doc_kind: str | None = None,
    status: str | None = None,
    tag: str | None = None,
):
    """Paginated index of every ingested document — each is a 'ticket' with its
    extracted metadata. Filter on q / collection / year / group / doc_kind /
    status / tag."""
    mf = {
        "collection": collection, "year": year, "group": group,
        "doc_kind": doc_kind, "status": status, "tag": tag,
    }
    async with SessionLocal() as session:
        return await list_documents(
            session, q=q, limit=limit, offset=offset,
            meta_filters={k: v for k, v in mf.items() if v},
        )


class DocMetaPatch(BaseModel):
    status: str | None = None                 # new | open | reviewed | closed | ...
    add_tags: list[str] | None = None
    remove_tags: list[str] | None = None
    set: dict | None = None                   # arbitrary metadata keys to set


@app.patch("/documents/{document_id}/meta", dependencies=auth)
async def patch_document_meta(document_id: str, patch: DocMetaPatch):
    """Update a document's ticket fields (status / tags / other metadata).
    This is how a text file becomes a managed ticket you can track."""
    async with SessionLocal() as session:
        doc = await session.get(Document, document_id)
        if doc is None:
            raise HTTPException(404, "no such document")
        meta = dict(doc.doc_metadata or {})
        if patch.status is not None:
            meta["status"] = patch.status
        tags = list(meta.get("tags", []) or [])
        for t in (patch.add_tags or []):
            if t and t not in tags:
                tags.append(t)
        for t in (patch.remove_tags or []):
            if t in tags:
                tags.remove(t)
        if patch.add_tags is not None or patch.remove_tags is not None:
            meta["tags"] = tags
        for k, v in (patch.set or {}).items():
            meta[k] = v
        doc.doc_metadata = meta
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(doc, "doc_metadata")
        await session.commit()
        return {"id": document_id, "metadata": meta}


@app.get("/documents/{document_id}", dependencies=auth)
async def document_detail(document_id: str):
    """One document: full text plus every chunk it was split into."""
    async with SessionLocal() as session:
        doc = await get_document(session, document_id)
    if doc is None:
        raise HTTPException(404, "No such document")
    return doc


# --------------------------------------------------------------------------- #
# Orchestration layer
# --------------------------------------------------------------------------- #
class AssistantRequest(BaseModel):
    text: str
    # query | law | cases | agent | archive | analytics | chat — skips the router.
    intent: str | None = None
    model: str | None = None
    # With intent="archive": start a persisted pipeline run in this mode
    # (review | steps | auto | conversation) instead of returning a bare draft.
    mode: str | None = None


class CommitRequest(BaseModel):
    draft: dict
    raw_text: str
    source: str


@app.post("/assistant", dependencies=auth)
async def assistant(req: AssistantRequest):
    """Route one message: query the archive, draft an archive entry, or
    return analytics. Archive drafts are NOT written — confirm via
    POST /assistant/commit."""
    llm = _llm(req.model)
    if not llm.is_available():
        raise HTTPException(503, "LLM provider is not available.")
    async with SessionLocal() as session:
        if req.intent == "archive" and req.mode:
            return await _start_run(session, llm, req.text, mode=req.mode, source=None)
        return await run_assistant(session, llm, req.text, force_intent=req.intent)


def _run_reply(view: dict) -> dict:
    """A run view plus the conversation's next question, when it is waiting."""
    return {"run": view, "waiting": conversation.is_waiting(view),
            "message": conversation.last_question(view) if conversation.is_waiting(view) else None}


async def _start_run(session, llm, text: str, *, mode: str, source: str | None) -> dict:
    import datetime as _dt

    if mode not in workflow.RUN_MODES:
        raise HTTPException(422, f"mode must be one of {', '.join(workflow.RUN_MODES)}")
    view = await workflow.start(
        session, raw_text=text, source=source or f"api/{_dt.datetime.now():%Y%m%d-%H%M%S}",
        llm=llm, mode=mode, forced_intent="archive",
    )
    return {"intent": "archive", **_run_reply(view)}


class RunStartRequest(BaseModel):
    text: str
    source: str | None = None
    mode: str = "review"   # review | steps | auto | conversation
    model: str | None = None


class RunReplyRequest(BaseModel):
    text: str
    model: str | None = None


@app.post("/runs", dependencies=auth)
async def runs_start(req: RunStartRequest):
    """Start a persisted entry-building run (the same engine the chat uses).
    In `conversation` mode the response carries the assistant's question;
    answer it with POST /runs/{run_id}/reply."""
    llm = _llm(req.model)
    if not llm.is_available():
        raise HTTPException(503, "LLM provider is not available.")
    async with SessionLocal() as session:
        return await _start_run(session, llm, req.text, mode=req.mode, source=req.source)


@app.post("/runs/{run_id}/reply", dependencies=auth)
async def runs_reply(run_id: str, req: RunReplyRequest):
    """One turn of a conversation-mode run: merge the reply, re-ask or commit."""
    llm = _llm(req.model)
    async with SessionLocal() as session:
        try:
            view = await conversation.turn(session, run_id, llm, req.text)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        return _run_reply(view)


@app.post("/assistant/commit", dependencies=auth)
async def assistant_commit(req: CommitRequest):
    async with SessionLocal() as session:
        entry = await commit_entry(session, req.draft, req.raw_text, source=req.source)
        return {
            "id": str(entry.id),
            "title": entry.title,
            "document_id": str(entry.document_id) if entry.document_id else None,
            "related_ids": entry.related_ids,
        }


@app.get("/answers", dependencies=auth)
async def answers_list(
    limit: int = Query(default=50, ge=1, le=500), intent: str | None = None,
):
    """Answered questions with their provenance blocks, newest first."""
    async with SessionLocal() as session:
        query = select(AssistantAnswer).order_by(AssistantAnswer.created_at.desc()).limit(limit)
        if intent:
            query = query.where(AssistantAnswer.intent == intent)
        rows = (await session.execute(query)).scalars().all()
    return {"answers": [prov.answer_view(r) for r in rows]}


@app.get("/answers/{answer_id}", dependencies=auth)
async def answers_detail(answer_id: str):
    async with SessionLocal() as session:
        row = await session.get(AssistantAnswer, answer_id)
    if row is None:
        raise HTTPException(404, "No such answer")
    return prov.answer_view(row)


@app.get("/stats", dependencies=auth)
async def stats():
    async with SessionLocal() as session:
        return await corpus_stats(session)


class EvalRequest(BaseModel):
    path: str = "eval/farsi.jsonl"
    top_k: int = Field(default=5, ge=1, le=20)
    with_answers: bool = False
    model: str | None = None


@app.post("/eval", dependencies=auth)
async def eval_run(req: EvalRequest):
    """Score the retriever against an eval set. Fast by default (retrieval
    only); with_answers=true also runs the LLM per query (slow). Switch
    `model` / the embedding model and re-run to compare."""
    from pathlib import Path as _P

    from app.rag.evaluate import load_cases, run_eval

    p = _P(req.path)
    if not p.exists():
        raise HTTPException(404, f"No eval file at {req.path}")
    cases = load_cases(p)
    llm = _llm(req.model) if req.with_answers else None
    async with SessionLocal() as session:
        result = await run_eval(session, cases, top_k=req.top_k, llm=llm)
    result["embedding_model"] = settings.embedding_model
    result["llm_model"] = getattr(llm, "model", None) if llm else None
    return result


class BenchRequest(BaseModel):
    questions: list[str] = Field(min_length=1, max_length=20)
    model_ids: list[str] = Field(min_length=1, max_length=8)
    top_k: int = Field(default=5, ge=1, le=20)


@app.post("/bench", dependencies=auth)
async def bench(req: BenchRequest):
    """Run the same questions through several models side by side. Retrieval
    happens once per question (identical across LLMs) and is reused; only the
    generation step varies. Returns a question x model grid plus a per-model
    latency summary — the data behind the Bench tab.

    The grid itself lives in `app.rag.bench` so the Streamlit UI runs the exact
    same benchmark rather than a second, drifting copy."""
    async with SessionLocal() as session:
        try:
            return await run_bench(session, req.questions, req.model_ids, top_k=req.top_k)
        except NothingIndexed as exc:
            raise HTTPException(409, str(exc))
        except ValueError as exc:
            raise HTTPException(400, str(exc))


@app.get("/entries", dependencies=auth)
async def entries():
    async with SessionLocal() as session:
        return await catalog.list_entries(session, limit=2000)


@app.get("/entries/{entry_id}", dependencies=auth)
async def get_entry(entry_id: str):
    async with SessionLocal() as session:
        row = await catalog.get_entry(session, entry_id)
        if row is None:
            raise HTTPException(404, "No such entry")
        return row


@app.patch("/entries/{entry_id}", dependencies=auth)
async def patch_entry(entry_id: str, patch: dict = Body(...)):
    """Edit any entry field; re-syncs the case, persons, citations and graph."""
    async with SessionLocal() as session:
        row = await catalog.update_entry(session, entry_id, patch)
        if row is None:
            raise HTTPException(404, "No such entry")
        return row


@app.delete("/entries/{entry_id}", dependencies=auth)
async def delete_entry(entry_id: str, with_document: bool = False):
    async with SessionLocal() as session:
        ok = await catalog.delete_entry(session, entry_id, with_document=with_document)
        if not ok:
            raise HTTPException(404, "No such entry")
    return {"deleted": entry_id}


# --------------------------------------------------------------------------- #
# Legal context (laws) · case archive · persons / organizations · graph
# --------------------------------------------------------------------------- #
@app.get("/laws", dependencies=auth)
async def laws(law_title: str | None = None, q: str | None = None, limit: int = 500):
    async with SessionLocal() as session:
        if q:
            return {"items": await lawbase.search_laws(session, q, limit=min(limit, 50))}
        return {"titles": await lawbase.law_titles(session),
                "items": await lawbase.list_laws(session, law_title=law_title, limit=limit)}


@app.get("/laws/{ref_id}", dependencies=auth)
async def law(ref_id: str):
    async with SessionLocal() as session:
        row = await lawbase.get_ref(session, ref_id)
        if row is None:
            raise HTTPException(404, "No such reference")
        cases = await graph.neighborhood(session, "law", ref_id, depth=1)
        row["cited_by"] = [n for n in cases["nodes"] if n["type"] == "case"]
        return row


@app.post("/laws", dependencies=auth)
async def add_law(body: dict = Body(...)):
    async with SessionLocal() as session:
        ref = await lawbase.upsert_ref(
            session, law_title=body["law_title"], article_no=body.get("article_no"), text=body["text"],
            kind=body.get("kind", "law"), law_year=body.get("law_year"), title=body.get("title"),
            keywords=body.get("keywords") or [],
        )
        await session.commit()
        return lawbase.as_dict(ref)


@app.get("/cases", dependencies=auth)
async def cases(case_type: str | None = None, insurance_line: str | None = None, status: str | None = None,
                court: str | None = None, q: str | None = None, limit: int = 500):
    async with SessionLocal() as session:
        return {"items": await casebase.list_cases(
            session, case_type=case_type, insurance_line=insurance_line, status=status,
            court=court, q=q, limit=min(limit, 2000),
        )}


@app.get("/cases/search", dependencies=auth)
async def cases_search(q: str, limit: int = 8):
    async with SessionLocal() as session:
        return {"items": await casebase.search_cases(session, q, limit=min(limit, 50))}


@app.get("/cases/{case_id}", dependencies=auth)
async def case(case_id: str):
    async with SessionLocal() as session:
        row = await casebase.get_case(session, case_id)
        if row is None:
            raise HTTPException(404, "No such case")
        return row


@app.patch("/cases/{case_id}", dependencies=auth)
async def patch_case(case_id: str, patch: dict = Body(...)):
    async with SessionLocal() as session:
        row = await casebase.update_case(session, case_id, patch)
        if row is None:
            raise HTTPException(404, "No such case")
        await session.commit()
        return row


@app.get("/cases/{case_id}/similar", dependencies=auth)
async def case_similar(case_id: str, top_k: int = Query(default=5, ge=1, le=20)):
    """Cases resembling this one — shared articles, parties, court, labels,
    prior SIMILAR_TO links — each with the reasons and the graph path."""
    from app.rag import similar

    async with SessionLocal() as session:
        case = await casebase.get_case(session, case_id)
        if not case:
            raise HTTPException(404, "No such case")
        items = await similar.similar_cases(
            session, question=f"{case.get('title') or ''} {case.get('summary') or ''}",
            anchor_case_id=case["id"], top_k=top_k,
        )
        return {"case": {"id": case["id"], "case_number": case["case_number"], "title": case["title"]},
                "similar": items, "lessons": similar.outcome_lessons(items)}


@app.get("/graph/expand", dependencies=auth)
async def graph_expand(node_type: str, node_id: str, depth: int = Query(default=2, ge=1, le=3)):
    """Cases connected to any node through shared articles, parties, courts or
    labels, scored and explained (the model's `graph_expand` tool)."""
    from app.rag import similar

    async with SessionLocal() as session:
        return await similar.expand_for_tool(session, node_type, node_id, depth=depth)


@app.get("/cases/{case_id}/graph", dependencies=auth)
async def case_graph(case_id: str, depth: int = 1, format: str = "json"):
    async with SessionLocal() as session:
        row = await casebase.get_case(session, case_id)
        if row is None:
            raise HTTPException(404, "No such case")
        g = await graph.neighborhood(session, "case", row["id"], depth=min(max(depth, 1), 3))
        if format == "dot":
            return PlainTextResponse(graph.to_dot(g))
        if format == "cypher":
            return PlainTextResponse(graph.to_cypher(g))
        return g


@app.get("/entities/{kind}", dependencies=auth)
async def entities(kind: str, q: str | None = None, limit: int = 300):
    if kind not in ("person", "org"):
        raise HTTPException(400, "kind must be person or org")
    async with SessionLocal() as session:
        return {"items": await casebase.list_entities(session, kind, q=q, limit=min(limit, 1000))}


@app.get("/entities/{kind}/{key}", dependencies=auth)
async def entity(kind: str, key: str):
    if kind not in ("person", "org"):
        raise HTTPException(400, "kind must be person or org")
    async with SessionLocal() as session:
        prof = await casebase.entity_profile(session, kind, key)
        if prof is None:
            raise HTTPException(404, "No such entity")
        return prof


@app.get("/graph/{node_type}/{node_id}", dependencies=auth)
async def graph_node(node_type: str, node_id: str, depth: int = 1, format: str = "json"):
    if node_type not in graph.NODE_FA:
        raise HTTPException(400, f"node_type must be one of {sorted(graph.NODE_FA)}")
    async with SessionLocal() as session:
        g = await graph.neighborhood(session, node_type, node_id, depth=min(max(depth, 1), 3))
        if format == "dot":
            return PlainTextResponse(graph.to_dot(g))
        if format == "cypher":
            return PlainTextResponse(graph.to_cypher(g))
        return g


@app.get("/archive/stats", dependencies=auth)
async def archive_statistics():
    async with SessionLocal() as session:
        return await casebase.archive_stats(session)


@app.post("/archive/resync", dependencies=auth)
async def archive_resync():
    """Rebuild cases / persons / orgs / edges from every entry."""
    async with SessionLocal() as session:
        n = await casebase.resync_all(session)
        await session.commit()
        return {"entries": n}


@app.delete("/documents/{document_id}", dependencies=auth)
async def delete_document(document_id: str):
    async with SessionLocal() as session:
        doc = await session.get(Document, document_id)
        if doc is None:
            raise HTTPException(404, "No such document")
        await session.delete(doc)
        await session.commit()
    return {"deleted": document_id}


# --------------------------------------------------------------------------- #
# Webhooks — outbound subscriptions (signed, via the outbox) and inbound CI
# --------------------------------------------------------------------------- #
class HookCreate(BaseModel):
    url: str
    events: list[str] = ["*"]      # run.step | run.status | entry.committed | answer.created | ping | *
    description: str | None = None
    secret: str | None = None      # generated when omitted; returned once


@app.post("/hooks", dependencies=auth)
async def hooks_create(req: HookCreate):
    """Register a URL. The response carries the signing secret — the only
    time it is shown. Deliveries carry `X-Legal-Signature-256: sha256=<hmac>`."""
    async with SessionLocal() as session:
        try:
            sub = await hooks.create_subscription(
                session, url=req.url, events=req.events, description=req.description, secret=req.secret,
            )
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        return hooks.subscription_view(sub, with_secret=True)


@app.get("/hooks", dependencies=auth)
async def hooks_list():
    async with SessionLocal() as session:
        return {"hooks": [hooks.subscription_view(s) for s in await hooks.list_subscriptions(session)],
                "events": list(hooks.EVENTS)}


@app.delete("/hooks/{subscription_id}", dependencies=auth)
async def hooks_delete(subscription_id: str):
    async with SessionLocal() as session:
        if not await hooks.delete_subscription(session, subscription_id):
            raise HTTPException(404, "No such subscription")
    return {"deleted": subscription_id}


@app.post("/hooks/{subscription_id}/test", dependencies=auth)
async def hooks_test(subscription_id: str):
    """Queue a `ping` for one subscription and send it now."""
    async with SessionLocal() as session:
        sub = await session.get(hooks.WebhookSubscription, subscription_id)
        if sub is None:
            raise HTTPException(404, "No such subscription")
        delivery = hooks.WebhookDelivery(subscription_id=sub.id, event="ping",
                                         payload={"message": "سلام از آرشیو حقوقی", "subscription_id": str(sub.id)},
                                         status="pending", attempts=0)
        session.add(delivery)
        await session.commit()
        delivery_id = delivery.id
    await hooks.drain(SessionLocal)
    async with SessionLocal() as session:
        row = await session.get(hooks.WebhookDelivery, delivery_id)
        return hooks.delivery_view(row)


@app.get("/hooks/deliveries", dependencies=auth)
async def hooks_deliveries(subscription_id: str | None = None, status: str | None = None,
                           limit: int = Query(default=50, ge=1, le=500)):
    async with SessionLocal() as session:
        rows = await hooks.list_deliveries(session, subscription_id=subscription_id, status=status, limit=limit)
        return {"deliveries": [hooks.delivery_view(d) for d in rows]}


@app.post("/hooks/github")
async def hooks_github(request: Request):
    """GitHub → here. Verified with GITHUB_WEBHOOK_SECRET (503 while unset);
    `ping`, `workflow_run` and `workflow_job` are stored, others ignored."""
    secret = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
    if not secret:
        raise HTTPException(503, "GITHUB_WEBHOOK_SECRET is not configured")
    body = await request.body()
    if not hooks.verify(secret, body, request.headers.get("x-hub-signature-256")):
        raise HTTPException(401, "Bad signature")
    event = request.headers.get("x-github-event", "")
    delivery_id = request.headers.get("x-github-delivery") or f"github:{hooks.new_secret()[:16]}"
    if event not in ("ping", "workflow_run", "workflow_job"):
        return {"ignored": event}
    try:
        payload = json.loads(body.decode("utf-8") or "{}")
    except json.JSONDecodeError as error:
        raise HTTPException(400, "Body is not JSON") from error
    async with SessionLocal() as session:
        stored = await ci.record_github(session, delivery_id=delivery_id, event=event, payload=payload)
        await session.commit()
    return {"stored": stored, "event": event, "delivery_id": delivery_id}


@app.post("/ci/status", dependencies=ci_auth)
async def ci_status(body: dict = Body(...)):
    """A stage report from the workflow (`scripts/ci_status.sh`):
    {run_id, run_number, job, stage, status, conclusion?, sha, branch, url, ts}."""
    async with SessionLocal() as session:
        stored = await ci.record_status(session, body, source=body.get("source") or "ci-step")
        await session.commit()
    return {"ok": True, "stored": stored}


@app.get("/ci/events", dependencies=run_auth)
async def ci_events(limit: int = Query(default=10, ge=1, le=50)):
    """The latest CI runs with their jobs and stages, newest first."""
    async with SessionLocal() as session:
        return {"runs": await ci.list_ci_runs(session, limit=limit)}


@app.get("/ci/events/stream", dependencies=run_auth)
async def ci_events_stream(limit: int = Query(default=5, ge=1, le=20)):
    """SSE: the run list, re-sent whenever it changes (2 s polling)."""
    async def _stream():
        last = None
        for _ in range(900):  # 30 min ceiling
            async with SessionLocal() as session:
                runs = await ci.list_ci_runs(session, limit=limit)
            fingerprint = [(r["run_id"], r["updated_at"], r["status"], r["conclusion"]) for r in runs]
            if fingerprint != last:
                last = fingerprint
                yield f"data: {json.dumps({'runs': runs}, ensure_ascii=False, default=str)}\n\n"
            await asyncio.sleep(2)

    return StreamingResponse(_stream(), media_type="text/event-stream")


# --------------------------------------------------------------------------- #
# Build console — read-only view of the entry pipeline (app/rag/workflow.py).
# Runs are started and advanced from Streamlit; this is a window onto the
# `runs` / `run_steps` tables the two processes share.
# --------------------------------------------------------------------------- #
@app.get("/runs/view", include_in_schema=False)
@app.get("/runs/view/{run_id}", include_in_schema=False)
async def runs_view(run_id: str | None = None):
    """The build console — a self-contained page that reads /runs and
    /runs/{id}/events. Open (like /app); the API calls it makes carry ?token=.
    Registered before /runs/{run_id} so "view" is not read as a run id."""
    return FileResponse(STATIC_DIR / "runs.html")


@app.get("/runs", dependencies=run_auth)
async def runs_list(limit: int = Query(default=50, ge=1, le=200)):
    async with SessionLocal() as session:
        return {"runs": await run_store.list_runs(session, limit=limit)}


@app.get("/runs/{run_id}", dependencies=run_auth)
async def runs_detail(run_id: str):
    async with SessionLocal() as session:
        view = await run_store.load_run(session, run_id)
    if view is None:
        raise HTTPException(404, "No such run")
    return view


@app.get("/runs/{run_id}/events", dependencies=run_auth)
async def runs_events(run_id: str):
    """SSE: the run's step statuses, re-sent whenever they change.

    Polls the table (the run is usually driven from another process, so the
    in-process pub/sub would see nothing) and stops when the run is terminal.
    """
    async def _stream():
        last = None
        for _ in range(600):  # ~20 min ceiling at 2s
            async with SessionLocal() as session:
                view = await run_store.load_run(session, run_id)
            if view is None:
                yield "event: gone\ndata: {}\n\n"
                return
            fingerprint = [
                view["status"],
                *[(s["seq"], s["status"], s["ms"]) for s in view["steps"]],
            ]
            if fingerprint != last:
                last = fingerprint
                yield f"data: {json.dumps(view, ensure_ascii=False)}\n\n"
            if view["status"] in ("committed", "failed", "abandoned"):
                return
            await asyncio.sleep(2)

    return StreamingResponse(_stream(), media_type="text/event-stream")

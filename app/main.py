import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Header,
    HTTPException,
    Query,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.db.engine import create_schema, resolve_database_url
from app.db.models import Chunk, Document, Entry, Label
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
from app.rag.pipeline import SYSTEM_PROMPT, answer_question, build_prompt
from app.rag.retriever import effective_config, retrieve_scored
from app.rag import runs as run_store
from app.rag import transcribe as stt

engine = create_async_engine(resolve_database_url())
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_schema(engine)
    app.state.llm = get_llm_provider()
    app.state.model_id = registry.default_id()
    yield
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


auth = [Depends(require_token)]
run_auth = [Depends(require_run_access)]


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
        return AskResponse(**result.__dict__)


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
    intent: str | None = None  # "query" | "archive" | "analytics" to skip the router
    model: str | None = None


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
        return await run_assistant(session, llm, req.text, force_intent=req.intent)


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
        rows = (
            await session.execute(select(Entry).order_by(Entry.created_at.desc()))
        ).scalars().all()
        return [
            {
                "id": str(e.id),
                "kind": e.kind,
                "title": e.title,
                "summary": e.summary,
                "parties": e.parties,
                "representation": e.representation,
                "events": e.events,
                "entities": e.entities,
                "tags": e.tags,
                "related_ids": e.related_ids,
                "document_id": str(e.document_id) if e.document_id else None,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in rows
        ]


@app.delete("/entries/{entry_id}", dependencies=auth)
async def delete_entry(entry_id: str):
    async with SessionLocal() as session:
        e = await session.get(Entry, entry_id)
        if e is None:
            raise HTTPException(404, "No such entry")
        await session.delete(e)
        await session.commit()
    return {"deleted": entry_id}


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

"""
Chunk -> embed -> store. Shared by the CLI (`scripts/ingest.py`) and the
`/ingest` API endpoint so both behave identically.

`chunk_text()` is structure-aware: it splits on paragraph boundaries and on
Persian legal-document markers (ماده / تبصره / بند / رأی / گردشکار / تصمیم
دادگاه / numbered items), then packs whole blocks up to a target size instead
of cutting mid-sentence. Text is normalized (`normalize_fa`) first so the
lexical index matches regardless of how the source was typed.
"""

import asyncio
import re

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Chunk, Document
from app.rag.embeddings import embed_texts
from app.rag.textnorm import normalize_fa

# target size a packed chunk aims for; hard ceiling before a block is force-split
CHUNK_TARGET = 800
CHUNK_MAX = 1400
CHUNK_OVERLAP = 120

def collection_for(source: str) -> str:
    """A coarse bucket so retrieval / eval can be scoped to one body of material
    instead of the whole flat index. Stored on `Document.doc_metadata`."""
    s = str(source or "")
    if s.startswith("data/farsi-courts"):
        return "rulings"       # the bulk Iranian court-ruling dataset
    if s.startswith("data/farsi"):
        return "samples"       # the hand-curated Farsi session/contract samples
    if s.startswith("data/cases"):
        return "cases-en"      # the English common-law samples
    return "uploads"           # added via the UI / API / inbox


# a line that begins a new structural unit in an Iranian legal document
_STRUCT = re.compile(
    r"^\s*(?:"
    r"ماده\s|تبصره\b|بند\s|فصل\s|مبحث\s|"
    r"رأی\s|رای\s|گردش\s?کار|شرح\s+دادخواست|خلاصه(?:\s+اظهارات)?\b|"
    r"تصمیم\s+دادگاه|قرار\s+دادگاه|منطوق(?:\s+رأی)?|موضوع\b|"
    r"صورت\s?جلسه\b|دادنامه\b|"
    r"[0-9]{1,3}\s?[\-\.\)]\s|"          # 1-  1.  1)
    r"[الف-ی]\)\s"                       # الف)  ب)
    r")"
)
_SENT = re.compile(r"(?<=[.!؟?])\s+|\n")


def _blocks(text: str) -> list[str]:
    """Paragraphs, further broken where a line starts a new structural unit."""
    out: list[str] = []
    for para in re.split(r"\n\s*\n", text):
        cur: list[str] = []
        for line in para.splitlines():
            if cur and _STRUCT.match(line):
                out.append("\n".join(cur))
                cur = [line]
            else:
                cur.append(line)
        if cur:
            out.append("\n".join(cur))
    return [b.strip() for b in out if b.strip()]


def _split_long(block: str) -> list[str]:
    """A single block over CHUNK_MAX: pack sentences up to the target size."""
    chunks: list[str] = []
    cur = ""
    for sent in _SENT.split(block):
        sent = sent.strip()
        if not sent:
            continue
        if cur and len(cur) + len(sent) + 1 > CHUNK_TARGET:
            chunks.append(cur.strip())
            cur = cur[-CHUNK_OVERLAP:] + " "
        cur += sent + " "
        while len(cur) > CHUNK_MAX:
            chunks.append(cur[:CHUNK_MAX].strip())
            cur = cur[CHUNK_MAX - CHUNK_OVERLAP:]
    if cur.strip():
        chunks.append(cur.strip())
    return chunks


def chunk_text(text: str) -> list[str]:
    text = normalize_fa(text).strip()
    if not text:
        return []
    if len(text) <= CHUNK_MAX:
        return [text]

    chunks: list[str] = []
    cur = ""
    for block in _blocks(text):
        if len(block) > CHUNK_MAX:
            if cur.strip():
                chunks.append(cur.strip())
                cur = ""
            chunks.extend(_split_long(block))
            continue
        if cur and len(cur) + len(block) + 1 > CHUNK_TARGET:
            chunks.append(cur.strip())
            cur = cur.strip()[-CHUNK_OVERLAP:] + "\n"
        cur += block + "\n"
    if cur.strip():
        chunks.append(cur.strip())

    # fold a tiny trailing chunk back into its predecessor
    if len(chunks) > 1 and len(chunks[-1]) < CHUNK_TARGET // 3:
        chunks[-2] = chunks[-2] + "\n" + chunks[-1]
        chunks.pop()
    return [c for c in chunks if c]


async def ingest_document(
    session: AsyncSession,
    *,
    text: str,
    source: str,
    title: str | None = None,
    metadata: dict | None = None,
    replace: bool = False,
) -> tuple[Document | None, str]:
    """
    Returns (document, status) where status is one of
    "created" | "replaced" | "skipped" | "empty".
    Caller is responsible for committing.
    """
    existing = await session.scalar(select(Document).where(Document.source == source))
    if existing is not None:
        if not replace:
            return None, "skipped"
        await session.delete(existing)
        await session.flush()

    pieces = chunk_text(text)
    if not pieces:
        return None, "empty"

    if not title:
        first_line = text.strip().splitlines()[0] if text.strip() else source
        title = first_line[:200]

    vectors = await asyncio.to_thread(embed_texts, pieces)

    from app.rag.metadata import extract_metadata

    meta = {**extract_metadata(text), **(metadata or {})}  # explicit metadata wins
    meta.setdefault("collection", collection_for(source))
    doc = Document(source=source, title=title, raw_text=text, doc_metadata=meta)
    doc.chunks = [
        Chunk(text=piece, embedding=vec, chunk_index=i)
        for i, (piece, vec) in enumerate(zip(pieces, vectors))
    ]
    session.add(doc)
    await session.flush()
    return doc, ("replaced" if existing is not None else "created")


async def reset_all(session: AsyncSession) -> None:
    await session.execute(delete(Chunk))
    await session.execute(delete(Document))


async def list_documents(
    session: AsyncSession,
    *,
    q: str | None = None,
    limit: int | None = None,
    offset: int = 0,
    meta_filters: dict | None = None,
) -> dict:
    """Paginated document index. `q` matches title/source/case number.
    `meta_filters` restricts on Document.doc_metadata (collection / year /
    group / status / doc_kind / ...). Returns {"total", "items"} — each item
    carries its metadata so the UI can render it as a ticket."""
    where = []
    if q:
        like = f"%{q}%"
        where.append(
            Document.title.ilike(like)
            | Document.source.ilike(like)
            | Document.doc_metadata["case_number"].astext.ilike(like)
        )
    for key, val in (meta_filters or {}).items():
        if val not in (None, ""):
            if key == "tag":
                where.append(Document.doc_metadata["tags"].astext.ilike(f'%"{val}"%'))
            else:
                where.append(Document.doc_metadata[key].astext == str(val))

    total = await session.scalar(
        select(func.count()).select_from(Document).where(*where)
    )

    stmt = (
        select(
            Document.id,
            Document.title,
            Document.source,
            Document.created_at,
            Document.doc_metadata,
            func.count(Chunk.id).label("chunks"),
        )
        .outerjoin(Chunk, Chunk.document_id == Document.id)
        .where(*where)
        .group_by(Document.id)
        .order_by(Document.created_at.desc())
        .offset(offset)
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    rows = (await session.execute(stmt)).all()
    return {
        "total": total or 0,
        "items": [
            {
                "id": str(r.id),
                "title": r.title,
                "source": r.source,
                "chunks": r.chunks,
                "metadata": r.doc_metadata or {},
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


async def get_document(session: AsyncSession, document_id: str) -> dict | None:
    doc = await session.get(Document, document_id)
    if doc is None:
        return None
    chunks = (
        await session.execute(
            select(Chunk.chunk_index, Chunk.text)
            .where(Chunk.document_id == doc.id)
            .order_by(Chunk.chunk_index)
        )
    ).all()
    return {
        "id": str(doc.id),
        "title": doc.title,
        "source": doc.source,
        "doc_metadata": doc.doc_metadata,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "raw_text": doc.raw_text,
        "chunks": [{"chunk_index": c.chunk_index, "text": c.text} for c in chunks],
    }

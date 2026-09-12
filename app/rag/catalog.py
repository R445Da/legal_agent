"""
Catalog queries: collections, facets, the schema overview, entries and labels.

These were written inline inside FastAPI route bodies, which made them
unreachable from anything that isn't an HTTP request. They are plain database
reads with no web-framework content, so they belong here — the Streamlit UI
imports them directly and `app/main.py` calls the same functions.
"""

import math

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import TS_CONFIG, Chunk, Document, Entry, Label

FACET_KEYS = ("year", "group", "doc_kind", "branch", "status")

# Persian labels for the metadata facets and the built-in collections, so the UI
# never shows a raw key to a user.
FACET_FA = {
    "year": "سال", "group": "گروه", "doc_kind": "نوع سند",
    "branch": "شعبه", "status": "وضعیت",
}
COLLECTION_FA = {
    "samples": "نمونه‌های دستی", "rulings": "آرای دادگاه‌ها",
    "cases-en": "نمونه‌های انگلیسی", "uploads": "افزوده‌شده",
}


async def collections(session: AsyncSession) -> dict:
    """The document buckets retrieval can be scoped to, with counts."""
    rows = (
        await session.execute(
            select(
                Document.doc_metadata["collection"].astext.label("name"),
                func.count().label("documents"),
            ).group_by("name")
        )
    ).all()
    return {
        "collections": [{"name": r.name or "uploads", "documents": r.documents} for r in rows],
        "total_documents": sum(r.documents for r in rows),
    }


async def facets(session: AsyncSession) -> dict:
    """Distinct metadata values (with counts) that retrieval can filter on."""
    out: dict = {}
    for key in FACET_KEYS:
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


async def counts(session: AsyncSession) -> dict:
    docs = await session.scalar(select(func.count()).select_from(Document))
    chunks = await session.scalar(select(func.count()).select_from(Chunk))
    entries = await session.scalar(select(func.count()).select_from(Entry))
    return {"documents": docs or 0, "chunks": chunks or 0, "entries": entries or 0}


async def schema_overview(session: AsyncSession) -> dict:
    """What the system stores and how — so the UI can explain itself."""
    from app.rag.orchestrator import ENTRY_SCHEMA

    n = await counts(session)
    avg_chunks = round(n["chunks"] / n["documents"], 1) if n["documents"] else 0
    return {
        "model": [
            {
                "name": "Document", "fa": "سند",
                "what": "یک سند/متن خام همان‌طور که وارد شده",
                "count": n["documents"],
                "fields": ["source (کلید یکتا)", "title", "raw_text", "doc_metadata (شامل collection)", "created_at"],
            },
            {
                "name": "Chunk", "fa": "قطعه",
                "what": f"تکه‌های سند برای بازیابی؛ هر قطعه یک بردار تعبیه و یک نمایهٔ متنی دارد. میانگین {avg_chunks} قطعه در هر سند.",
                "count": n["chunks"],
                "fields": [
                    f"embedding (بردار {settings.embedding_model.split('/')[-1]})",
                    "text (نرمال‌شده)", "text_search (tsvector)", "chunk_index",
                ],
            },
            {
                "name": "Entry", "fa": "مدخل ساختاریافته",
                "what": "دادهٔ استخراج‌شده از یک جلسه/سند — همان چیزی که نمای «پرونده‌ها» از آن ساخته می‌شود",
                "count": n["entries"],
                "fields": [f["label"] for f in ENTRY_SCHEMA["fields"]],
            },
        ],
        "entry_form": ENTRY_SCHEMA,
        "pipeline": {
            "query": ["نرمال‌سازی", "تعبیهٔ پرسش", "جستجوی برداری", "جستجوی متنی (BM25-وار)", "ترکیب RRF", "بازرتبه‌بندی", "تولید پاسخ"],
            "archive": ["تشخیص نوع", "استخراج ساختاریافته ✋", "خط زمان ✋", "پرونده‌های مشابه (ابزار) ✋", "برچسب‌ها ✋", "ثبت + نمایه‌سازی"],
            "analytics": ["تشخیص نوع", "تجمیع SQL", "خلاصهٔ زبانی"],
        },
        "pipeline_note": "✋ = توقف برای تأیید شما. هر اجرا در جدول runs ذخیره می‌شود و در «کارگاه ساخت» (localhost:8000/runs/view) قابل مشاهده است.",
    }


async def list_entries(session: AsyncSession, limit: int = 500) -> list[dict]:
    """Every structured entry, newest first — the source the case view folds."""
    rows = (
        await session.execute(select(Entry).order_by(Entry.created_at.desc()).limit(limit))
    ).scalars().all()
    return [
        {
            "id": str(e.id),
            "document_id": str(e.document_id) if e.document_id else None,
            "kind": e.kind,
            "title": e.title,
            "summary": e.summary,
            "entities": e.entities or {},
            "parties": e.parties or [],
            "events": e.events or [],
            "representation": e.representation or [],
            "tags": e.tags or [],
            "related_ids": e.related_ids or [],
            "related": e.related or [],
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in rows
    ]


# --------------------------------------------------------------------------- #
# Labels — human judgments that feed retrieval evaluation and tuning
# --------------------------------------------------------------------------- #
async def add_label(
    session: AsyncSession, *, kind: str, target_type: str, target_id: str,
    value: str | None = None, query: str | None = None,
    note: str | None = None, labeled_by: str | None = None,
) -> dict:
    """Record a judgment. For relevance/review labels the (kind, target, query)
    triple is unique — re-recording updates the value so 👍/👎 can toggle."""
    existing = None
    if kind in ("relevance", "review"):
        existing = await session.scalar(
            select(Label).where(
                Label.kind == kind,
                Label.target_type == target_type,
                Label.target_id == target_id,
                Label.query == query,
            )
        )
    if existing:
        existing.value = value
        existing.note = note or existing.note
        label = existing
    else:
        label = Label(
            kind=kind, target_type=target_type, target_id=target_id,
            value=value, query=query, note=note, labeled_by=labeled_by,
        )
        session.add(label)
    await session.commit()
    await session.refresh(label)
    return {"id": str(label.id), "kind": label.kind, "value": label.value}


async def list_labels(
    session: AsyncSession, *, kind: str | None = None,
    target_type: str | None = None, target_id: str | None = None, limit: int = 200,
) -> list[dict]:
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
            "note": r.note,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


async def delete_label(session: AsyncSession, label_id: str) -> bool:
    label = await session.get(Label, label_id)
    if label is None:
        return False
    await session.delete(label)
    await session.commit()
    return True

# --------------------------------------------------------------------------- #
# Finding entries by what a question is actually about
# --------------------------------------------------------------------------- #
async def search_entries(session: AsyncSession, text: str, *, limit: int = 8) -> list:
    """Entries matching a question, ranked by Postgres full-text relevance.

    This used to be a pile of ILIKEs with a hand-rolled score, and it could not
    be made to work: requiring every word found nothing when a word like
    «تصمیمی» appeared in no entry, while accepting any word let «گرفت» — in half
    the archive — bury «معیوب», the one word that identified the case. Inverse
    document frequency helped but still let incidental rare words outrank the
    subject of the question.

    `ts_rank_cd` over a stored `tsvector` does the weighting properly and in the
    index: rare terms count for more, term proximity counts, and the ranking is
    the same machinery the chunk half of retrieval already uses. The query is
    folded through `normalize_fa` because the column was built with the same
    character map.
    """
    from app.rag.textnorm import normalize_fa

    tokens = [
        token.strip("؟?.,،:؛«»\"'()[]")
        for token in normalize_fa(text or "").split()
    ]
    tokens = [token for token in tokens if len(token) >= 3]
    if not tokens:
        return []

    # `ts_rank_cd` alone is not enough here. TS_CONFIG is "simple", which has no
    # stopword list — Persian isn't one of Postgres' built-in configurations —
    # so «پرونده» and «دادگاه» carry the same weight as «معیوب» and every query
    # ranks the same handful of short entries first.
    #
    # So the terms are filtered before they are ranked: ask the index how many
    # entries each one appears in, and drop the ones that describe most of the
    # archive. What is left is what the question is actually about, and
    # `ts_rank_cd` then orders those properly, using term frequency and
    # proximity, inside the index.
    total = await session.scalar(select(func.count()).select_from(Entry)) or 0
    if not total:
        return []

    frequency: dict[str, int] = {}
    for token in set(tokens):
        frequency[token] = await session.scalar(
            select(func.count()).select_from(Entry).where(
                Entry.text_search.op("@@")(func.to_tsquery(TS_CONFIG, token))
            )
        ) or 0

    ceiling = total * 0.5
    useful = [t for t, n in frequency.items() if 0 < n <= ceiling]
    if not useful:
        # Every term is either absent or ubiquitous; fall back to the rarest
        # one that matches anything at all rather than returning nothing.
        present = sorted((n, t) for t, n in frequency.items() if n)
        if not present:
            return []
        useful = [present[0][1]]

    tsquery = func.to_tsquery(TS_CONFIG, " | ".join(useful))
    rank = func.ts_rank_cd(Entry.text_search, tsquery)

    rows = (await session.execute(
        select(Entry)
        .where(Entry.text_search.op("@@")(tsquery))
        .order_by(rank.desc())
        .limit(limit)
    )).scalars().all()
    return list(rows)

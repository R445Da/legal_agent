"""
Catalog queries: collections, facets, the schema overview, entries and labels.

These were written inline inside FastAPI route bodies, which made them
unreachable from anything that isn't an HTTP request. They are plain database
reads with no web-framework content, so they belong here — the Streamlit UI
imports them directly and `app/main.py` calls the same functions.
"""


from sqlalchemy import func, select
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

    from app.rag.casebase import archive_stats

    n = await counts(session)
    g = await archive_stats(session)
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
            {
                "name": "LegalCase", "fa": "پرونده",
                "what": "یک ردیف به ازای هر شمارهٔ پرونده — نوع دعوا، رشتهٔ بیمه، مرجع، وضعیت، نتیجه، مبلغ. مدخل‌ها به آن متصل‌اند.",
                "count": g["cases"],
                "fields": ["case_number (کلید)", "case_type", "insurance_line", "court", "status", "stage", "filed_date", "outcome", "claim_amount"],
            },
            {
                "name": "LegalReference", "fa": "مادهٔ قانونی (بافت حقوقی)",
                "what": "قوانین، آیین‌نامه‌ها و آرای وحدت رویه‌ای که دادگاه به آن‌ها ارجاع می‌دهد — طبقه‌بندی اول",
                "count": g["laws"],
                "fields": ["law_title", "article_no", "kind (law/regulation/precedent)", "text", "keywords", "text_search"],
            },
            {
                "name": "Person / Organization", "fa": "شخص / سازمان",
                "what": "هر وکیل، قاضی، طرف دعوا، شرکت بیمه و مرجع یک ردیف است تا بتوان پروفایلش را باز کرد",
                "count": g["persons"] + g["orgs"],
                "fields": ["name", "norm_name (کلید ادغام)", "roles", "kind"],
            },
            {
                "name": "GraphEdge", "fa": "یال گراف",
                "what": "گراف دانش: پرونده → مدخل/سند/شخص/سازمان/ماده/برچسب. جدول‌های case_parties و case_references حقیقت رابطه‌ای‌اند و این جدول همان را برای پیمایش و خروجی Cypher تخت می‌کند.",
                "count": g["citations"],
                "fields": ["src_type/src_id", "relation (PARTY, CITES, REPRESENTS, HEARD_AT, …)", "dst_type/dst_id", "weight", "meta"],
            },
        ],
        "entry_form": ENTRY_SCHEMA,
        "pipeline": {
            "query": ["نرمال‌سازی", "تعبیهٔ پرسش", "جستجوی برداری", "جستجوی متنی (BM25-وار)", "ترکیب RRF", "بازرتبه‌بندی", "تولید پاسخ"],
            "law": ["تشخیص نوع", "جستجوی متنی در پایگاه قوانین", "پاسخ با استناد به مواد [n]"],
            "cases": ["تشخیص نوع", "جستجوی متنی در جدول پرونده‌ها", "بارگذاری طرفین و مستندات هر پرونده", "پاسخ با استناد به پرونده‌ها [n]"],
            "archive": ["تشخیص نوع", "استخراج ساختاریافته ✋", "مستندات قانونی ✋", "خط زمان ✋", "پرونده‌های مشابه (ابزار) ✋", "برچسب‌ها ✋", "ثبت + نمایه‌سازی + گراف"],
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
            "legal_refs": e.legal_refs or [],
            "case_id": str(e.case_id) if e.case_id else None,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in rows
    ]


def entry_dict(e: Entry) -> dict:
    return {
        "id": str(e.id),
        "document_id": str(e.document_id) if e.document_id else None,
        "kind": e.kind, "title": e.title, "summary": e.summary,
        "entities": e.entities or {}, "parties": e.parties or [], "events": e.events or [],
        "representation": e.representation or [], "tags": e.tags or [],
        "related_ids": e.related_ids or [], "related": e.related or [],
        "legal_refs": e.legal_refs or [], "case_id": str(e.case_id) if e.case_id else None,
        "raw_text": e.raw_text,
        "created_at": e.created_at.isoformat() if e.created_at else None,
    }


async def get_entry(session: AsyncSession, entry_id: str) -> dict | None:
    import uuid

    try:
        row = await session.get(Entry, uuid.UUID(str(entry_id)))
    except ValueError:
        return None
    return entry_dict(row) if row else None


ENTRY_EDITABLE = ("kind", "title", "summary", "parties", "representation", "events", "entities", "tags", "legal_refs")


async def update_entry(session: AsyncSession, entry_id: str, patch: dict) -> dict | None:
    """Edit any field of an entry, then re-sync its case / persons / citations /
    graph edges so the relational side never drifts from the JSON. Unknown keys
    are ignored; `entities` is merged, everything else is replaced."""
    import uuid

    from app.rag import casebase, lawbase

    row = await session.get(Entry, uuid.UUID(str(entry_id)))
    if row is None:
        return None
    for key in ENTRY_EDITABLE:
        if key not in patch:
            continue
        value = patch[key]
        if key == "entities":
            merged = {**(row.entities or {}), **(value or {})}
            row.entities = {k: ("" if v is None else v) for k, v in merged.items()}
        elif key == "legal_refs":
            refs = [r for r in (value or []) if isinstance(r, dict) and (r.get("law") or r.get("text"))]
            row.legal_refs = await lawbase.resolve_refs(session, refs, create_stubs=True)
        elif key == "tags":
            row.tags = [str(t).strip() for t in (value or []) if str(t).strip()]
        else:
            setattr(row, key, value)
    # Tag labels mirror the JSON column (the taxonomy view reads Label rows).
    if "tags" in patch:
        from sqlalchemy import delete

        await session.execute(delete(Label).where(
            Label.kind == "tag", Label.target_type == "entry", Label.target_id == str(row.id)
        ))
        for tag in row.tags or []:
            session.add(Label(kind="tag", target_type="entry", target_id=str(row.id), value=tag, labeled_by="editor"))
    await session.flush()
    await casebase.sync_entry(session, row)
    await session.commit()
    await session.refresh(row)
    return entry_dict(row)


async def delete_entry(session: AsyncSession, entry_id: str, *, with_document: bool = False) -> bool:
    import uuid

    from sqlalchemy import delete

    from app.db.models import LegalCase
    from app.rag import graph

    try:
        row = await session.get(Entry, uuid.UUID(str(entry_id)))
    except ValueError:
        return False
    if row is None:
        return False
    case_id, doc_id = row.case_id, row.document_id
    await graph.unlink_node(session, "entry", row.id)
    await session.execute(delete(Label).where(Label.target_type == "entry", Label.target_id == str(row.id)))
    await session.delete(row)
    await session.flush()
    if with_document and doc_id:
        doc = await session.get(Document, doc_id)
        if doc:
            await session.delete(doc)
    if case_id:
        # Re-sync the case from its remaining entries, or drop it when empty.
        remaining = (await session.execute(select(Entry).where(Entry.case_id == case_id))).scalars().first()
        if remaining is not None:
            from app.rag import casebase
            await casebase.sync_entry(session, remaining)
        else:
            await graph.unlink_node(session, "case", case_id)
            case = await session.get(LegalCase, case_id)
            if case:
                await session.delete(case)
    from app.rag import casebase
    await casebase.prune_orphans(session)
    await session.commit()
    return True


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

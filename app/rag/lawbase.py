"""
The legal context: the laws, articles, regulations and precedents a court
refers to (`legal_refs`). This is the first of the two classifications the
graph relates — the other is the case archive (`casebase.py`).

Read paths (search, resolve a citation to a row, answer a legal question with
article citations) live here; the seed script and the pipeline write through
`upsert_ref`.
"""

from __future__ import annotations

import re

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import TS_CONFIG, LegalReference
from app.llm.base import LLMProvider
from app.rag.textnorm import normalize_fa

KIND_FA = {
    "law": "قانون", "regulation": "آیین‌نامه", "precedent": "رأی وحدت رویه",
    "circular": "بخشنامه", "stub": "ارجاع حل‌نشده",
}

_ARTICLE_RX = re.compile(r"(?:ماد[هﻩ]|تبصر[هﻩ]|بند)\s*([0-9]+)")
_LAW_NOISE = ("قانون", "مصوب", "سال", "جمهوری اسلامی ایران", "ج.ا.ا")


def ref_key(law_title: str, article_no: str | None) -> str:
    """Stable key two citations of the same article agree on."""
    law = normalize_fa(law_title or "").strip()
    for noise in _LAW_NOISE:
        law = law.replace(noise, " ")
    law = re.sub(r"\b1[34][0-9]{2}\b", " ", law)      # a cited year is not part of the name
    law = " ".join(law.split())
    art = normalize_fa(str(article_no or "")).strip()
    art = re.sub(r"[^0-9a-zA-Z/]", "", art)
    return f"{law}|{art}"


def parse_citation(text: str) -> tuple[str, str | None]:
    """«ماده ۳۰ قانون بیمه» -> ("قانون بیمه", "30"). Best effort."""
    t = normalize_fa(text or "")
    m = _ARTICLE_RX.search(t)
    article = m.group(1) if m else None
    law = t[m.end():].strip() if m else t.strip()
    law = re.sub(r"^(?:ی|از|در)\s+", "", law)
    return (law or t.strip(), article)


async def upsert_ref(
    session: AsyncSession, *, law_title: str, article_no: str | None, text: str,
    kind: str = "law", law_year: str | None = None, title: str | None = None,
    keywords: list[str] | None = None,
) -> LegalReference:
    key = ref_key(law_title, article_no)
    stmt = insert(LegalReference).values(
        kind=kind, law_title=law_title, law_year=law_year, article_no=article_no,
        title=title, text=text, keywords=keywords or [], ref_key=key,
    ).on_conflict_do_update(
        index_elements=["ref_key"],
        set_={"text": text, "title": title, "kind": kind, "law_year": law_year,
              "keywords": keywords or []},
    ).returning(LegalReference.id)
    rid = await session.scalar(stmt)
    return await session.get(LegalReference, rid)


async def find_ref(session: AsyncSession, law_title: str, article_no: str | None) -> LegalReference | None:
    """Exact key first; then the same article number in a law whose folded
    title contains (or is contained in) the cited one."""
    key = ref_key(law_title, article_no)
    hit = await session.scalar(select(LegalReference).where(LegalReference.ref_key == key))
    if hit:
        return hit
    law, art = key.split("|", 1)
    if not law:
        return None
    candidates = (await session.execute(
        select(LegalReference).where(LegalReference.ref_key.like(f"%|{art}"))
    )).scalars().all()
    words = {w for w in law.split() if len(w) > 1}
    best, best_score = None, 0.0
    for c in candidates:
        c_law = c.ref_key.split("|", 1)[0]
        c_words = {w for w in c_law.split() if len(w) > 1}
        if not c_words or not words:
            continue
        shorter, longer = (words, c_words) if len(words) <= len(c_words) else (c_words, words)
        overlap = len(words & c_words) / len(shorter)
        # «بیمه» alone must not claim «بیمه اجباری شخص ثالث»: containment counts
        # only when the shorter name has at least two words.
        if overlap >= 0.99 and len(shorter) >= 2 and len(longer) - len(shorter) <= 2:
            return c
        if overlap > best_score:
            best, best_score = c, overlap
    return best if best_score >= 0.75 and len(words & {w for w in best.ref_key.split("|", 1)[0].split()}) >= 2 else None


async def resolve_refs(session: AsyncSession, refs: list[dict], *, create_stubs: bool = False) -> list[dict]:
    """Attach `ref_id` (and the canonical law/article) to each cited reference.
    Unresolved citations stay with ref_id=None — or become `stub` rows so the
    graph still has the node — and are flagged for the review gate."""
    out = []
    for raw in refs or []:
        if not isinstance(raw, dict):
            continue
        law = str(raw.get("law") or "").strip()
        article = str(raw.get("article") or "").strip() or None
        if not law and raw.get("text"):
            law, article = parse_citation(str(raw["text"]))
        if not law:
            continue
        row = await find_ref(session, law, article)
        if row is None and create_stubs:
            row = await upsert_ref(
                session, law_title=law, article_no=article, text="", kind="stub",
                title="ارجاع حل‌نشده — متن ماده در پایگاه نیست",
            )
        out.append({
            "law": row.law_title if row else law,
            "article": row.article_no if row else article,
            "context": str(raw.get("context") or "").strip(),
            "used_by": str(raw.get("used_by") or "").strip() or None,
            "ref_id": str(row.id) if row else None,
            "resolved": bool(row and row.kind != "stub"),
        })
    return out


async def list_laws(session: AsyncSession, *, law_title: str | None = None, limit: int = 500) -> list[dict]:
    q = select(LegalReference).order_by(LegalReference.law_title, LegalReference.article_no).limit(limit)
    if law_title:
        q = q.where(LegalReference.law_title == law_title)
    rows = (await session.execute(q)).scalars().all()
    return [as_dict(r) for r in rows]


async def law_titles(session: AsyncSession) -> list[dict]:
    rows = (await session.execute(
        select(LegalReference.law_title, LegalReference.kind, LegalReference.law_year,
               func.count().label("n"))
        .group_by(LegalReference.law_title, LegalReference.kind, LegalReference.law_year)
        .order_by(func.count().desc())
    )).all()
    return [{"law_title": r.law_title, "kind": r.kind, "law_year": r.law_year, "articles": r.n} for r in rows]


async def get_ref(session: AsyncSession, ref_id) -> dict | None:
    import uuid

    try:
        row = await session.get(LegalReference, uuid.UUID(str(ref_id)))
    except ValueError:
        return None
    return as_dict(row) if row else None


def as_dict(r: LegalReference) -> dict:
    return {
        "id": str(r.id), "kind": r.kind, "kind_fa": KIND_FA.get(r.kind, r.kind),
        "law_title": r.law_title, "law_year": r.law_year, "article_no": r.article_no,
        "title": r.title, "text": r.text, "keywords": r.keywords or [], "ref_key": r.ref_key,
        "cite": f"{'مادهٔ ' + r.article_no + ' ' if r.article_no else ''}{r.law_title}"
                + (f" ({r.law_year})" if r.law_year else ""),
    }


async def search_laws(session: AsyncSession, text: str, *, limit: int = 8) -> list[dict]:
    """Full-text search over the legal context, same DF-filtered `ts_rank_cd`
    recipe as `catalog.search_entries`. A bare «ماده ۳۰ قانون بیمه» resolves
    directly first."""
    law, article = parse_citation(text)
    if article:
        direct = await find_ref(session, law, article)
        if direct:
            return [as_dict(direct)]

    tokens = [t.strip("؟?.,،:؛«»\"'()[]") for t in normalize_fa(text or "").split()]
    tokens = [t for t in tokens if len(t) >= 3]
    if not tokens:
        return []
    total = await session.scalar(select(func.count()).select_from(LegalReference)) or 0
    if not total:
        return []
    freq: dict[str, int] = {}
    for tok in set(tokens):
        freq[tok] = await session.scalar(
            select(func.count()).select_from(LegalReference).where(
                LegalReference.text_search.op("@@")(func.to_tsquery(TS_CONFIG, tok))
            )
        ) or 0
    useful = [t for t, n in freq.items() if 0 < n <= total * 0.5]
    if not useful:
        present = sorted((n, t) for t, n in freq.items() if n)
        if not present:
            return []
        useful = [present[0][1]]
    tsq = func.to_tsquery(TS_CONFIG, " | ".join(useful))
    rank = func.ts_rank_cd(LegalReference.text_search, tsq)
    rows = (await session.execute(
        select(LegalReference).where(LegalReference.text_search.op("@@")(tsq))
        .order_by(rank.desc()).limit(limit)
    )).scalars().all()
    return [as_dict(r) for r in rows]


_LAW_SYSTEM = (
    "You are a Persian legal research assistant answering from the provided "
    "statute articles only. Cite every claim with the article number in "
    "brackets like [1]. Quote the operative words of the article when useful. "
    "If the articles do not settle the question, say so and name what would be "
    "needed. Reply in Persian."
)


async def answer_law_question(
    session: AsyncSession, llm: LLMProvider, question: str, *, top_k: int = 6, max_tokens: int = 1400,
) -> dict:
    """The «legal context» route: retrieve articles, answer with citations."""
    import time

    t0 = time.perf_counter()
    refs = await search_laws(session, question, limit=top_k)
    retrieve_ms = round((time.perf_counter() - t0) * 1000)
    if not refs:
        return {"answer": "مادهٔ قانونی مرتبطی در پایگاه قوانین یافت نشد.", "refs": [],
                "steps": [{"name": "جستجوی قوانین", "detail": "بدون نتیجه", "ms": retrieve_ms}]}
    excerpts = "\n\n".join(
        f"[{i}] {r['cite']}" + (f" — {r['title']}" if r.get("title") else "") + f"\n{r['text']}"
        for i, r in enumerate(refs, 1)
    )
    t1 = time.perf_counter()
    resp = await llm.generate(
        f"Articles:\n{excerpts}\n\nQuestion: {question}\n\nAnswer in Persian, citing [n].",
        system=_LAW_SYSTEM, max_tokens=max_tokens, reasoning_effort="low",
    )
    from app.llm.meter import usage_of

    return {
        "answer": resp.text, "refs": refs, "model": resp.model, "latency_ms": resp.latency_ms,
        "usage": usage_of([resp]), "reasoning": resp.reasoning,
        "steps": [
            {"name": "جستجوی قوانین", "detail": f"{len(refs)} ماده از پایگاه قوانین", "ms": retrieve_ms},
            {"name": "پاسخ با استناد به مواد", "detail": f"مدل {resp.model}",
             "ms": round((time.perf_counter() - t1) * 1000)},
        ],
    }

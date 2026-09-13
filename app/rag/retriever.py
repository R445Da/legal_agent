"""
Retrieval: a three-stage pipeline.

  1a. vector search      — query embedding vs. chunk embeddings (semantic recall)
  1b. lexical search     — Postgres full-text over chunk text (exact terms:
                           names, case numbers, statute refs)
  --> fuse 1a + 1b with Reciprocal Rank Fusion (RRF)
  2.  cross-encoder rerank — read each (query, chunk) pair together and score
                             true relevance; keep the top-k

Stage 1 is recall-oriented (cast a wide net, `RETRIEVE_CANDIDATES` per side).
Stage 2 is precision-oriented. Every stage is toggleable by env var so
`scripts/eval.py` can measure each one's contribution:

  HYBRID=0              vector only, skip lexical + RRF
  RERANK=0              skip the cross-encoder (return the fused order)
  RETRIEVE_CANDIDATES   per-side first-stage depth (default 30)
  RERANK_TOP            how many fused candidates the reranker reads (default 12)

`retrieve_scored` still returns `list[(Chunk, distance)]` where `distance` is
`1 - relevance` in [0, 1]; callers keep showing `1 - distance` as a score.
"""

import os
import re
import time

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import TS_CONFIG, Chunk, Document
from app.rag.embeddings import embed_query
from app.rag.rerank import rerank_scores
from app.rag.textnorm import normalize_fa

_HYBRID = os.environ.get("HYBRID", "1") != "0"
_RRF_K = int(os.environ.get("RRF_K", "60"))
# The lexical list is noisier than the vector list (a single shared word can
# float a weak match up), so it gets a lighter vote in the fusion. When the
# cross-encoder rerank is on this barely matters — it only sets the shortlist
# order — but with rerank off it's what the final ranking falls back to.
_LEX_WEIGHT = float(os.environ.get("RRF_LEX_WEIGHT", "0.5"))


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _query_tokens(query: str) -> list[str]:
    """Word-ish tokens for an OR full-text query, normalized the same way the
    stored chunk text is (ي->ی, ۱->1, ...) so they match."""
    return re.findall(r"\w{2,}", normalize_fa(query))[:24]


def _rrf(rank_lists: list[tuple[list, float]], k: int = _RRF_K) -> dict:
    """Reciprocal Rank Fusion over (ranked_ids, weight) pairs."""
    scores: dict = {}
    for lst, weight in rank_lists:
        for rank, key in enumerate(lst, start=1):
            scores[key] = scores.get(key, 0.0) + weight / (k + rank)
    return scores


async def retrieve(session: AsyncSession, query: str, top_k: int = 5) -> list[Chunk]:
    return [chunk for chunk, _ in await retrieve_scored(session, query, top_k=top_k)]


# metadata keys the retriever will filter on (Document.doc_metadata JSON).
FILTERABLE = ("collection", "year", "group", "case_number", "branch", "doc_kind")


def _apply_filters(stmt, collection: str | None, filters: dict | None,
                   document_ids: list | None = None):
    """`document_ids` restricts retrieval to named documents.

    Metadata filters match on what the ingester happened to parse out of a
    file, which is not always the number a case is filed under; a caller that
    already knows exactly which documents belong to a case — the case view does
    — should be able to say so rather than hope the strings agree.
    """
    conds = []
    if document_ids:
        stmt = stmt.where(Chunk.document_id.in_(list(document_ids)))
    if collection:
        conds.append(Document.doc_metadata["collection"].astext == collection)
    for key, val in (filters or {}).items():
        if key in FILTERABLE and val not in (None, ""):
            conds.append(Document.doc_metadata[key].astext == str(val))
    if not conds:
        return stmt
    return stmt.join(Chunk.document).where(*conds)


async def _vector_candidates(
    session: AsyncSession, query: str, limit: int,
    collection: str | None = None, filters: dict | None = None,
    document_ids: list | None = None,
) -> list[Chunk]:
    q_vec = await embed_query(normalize_fa(query))
    distance = Chunk.embedding.cosine_distance(q_vec)
    stmt = (
        select(Chunk)
        .options(selectinload(Chunk.document))
        .order_by(distance)
        .limit(limit)
    )
    return list((await session.execute(
        _apply_filters(stmt, collection, filters, document_ids))).scalars().all())


async def _lexical_candidates(
    session: AsyncSession, query: str, limit: int,
    collection: str | None = None, filters: dict | None = None,
    document_ids: list | None = None,
) -> list[Chunk]:
    tokens = _query_tokens(query)
    if not tokens:
        return []
    tsq = func.to_tsquery(TS_CONFIG, " | ".join(tokens))
    stmt = (
        select(Chunk)
        .options(selectinload(Chunk.document))
        .where(Chunk.text_search.op("@@")(tsq))
        .order_by(func.ts_rank_cd(Chunk.text_search, tsq).desc())
        .limit(limit)
    )
    return list((await session.execute(
        _apply_filters(stmt, collection, filters, document_ids))).scalars().all())


def effective_config(hybrid: bool | None = None, rerank: bool | None = None) -> dict:
    """What retrieve_scored would actually do, given optional per-call overrides.
    Used by the /search response so the retrieval lab can show the live pipeline."""
    from app.config import settings
    from app.rag.rerank import _MODEL_NAME, enabled as _rerank_enabled

    return {
        "hybrid": _HYBRID if hybrid is None else bool(hybrid),
        "rerank": _rerank_enabled() if rerank is None else bool(rerank),
        "embedding_model": settings.embedding_model,
        "rerank_model": _MODEL_NAME,
        "candidates_per_side": _int_env("RETRIEVE_CANDIDATES", 30),
        "rerank_top": _int_env("RERANK_TOP", 12),
        "rrf_lex_weight": _LEX_WEIGHT,
    }


async def retrieve_scored(
    session: AsyncSession,
    query: str,
    top_k: int = 5,
    *,
    hybrid: bool | None = None,
    rerank: bool | None = None,
    collection: str | None = None,
    filters: dict | None = None,
    document_ids: list | None = None,
    candidates: int | None = None,
    rerank_top: int | None = None,
    rerank_model: str | None = None,
    trace: dict | None = None,
) -> list[tuple[Chunk, float]]:
    """`candidates` / `rerank_top` / `rerank_model` override the env defaults for
    one call — the two cost dials plus the model, so the UI can measure the
    reranker's price without an .env edit and a restart.

    Pass a dict as `trace` to have per-stage wall-clock milliseconds written
    into it (`vector_ms`, `lexical_ms`, `rerank_ms`, `pairs_scored`).
    """
    use_hybrid = _HYBRID if hybrid is None else bool(hybrid)
    n_candidates = max(candidates or _int_env("RETRIEVE_CANDIDATES", 30), top_k)
    n_rerank_top = max(rerank_top or _int_env("RERANK_TOP", 12), top_k)

    t0 = time.perf_counter()
    vec_rows = await _vector_candidates(session, query, n_candidates, collection, filters, document_ids)
    t1 = time.perf_counter()
    lex_rows = (await _lexical_candidates(session, query, n_candidates, collection, filters, document_ids)
                if use_hybrid else [])
    t2 = time.perf_counter()

    if trace is not None:
        trace["vector_ms"] = (t1 - t0) * 1000
        trace["lexical_ms"] = (t2 - t1) * 1000

    by_id: dict = {c.id: c for c in vec_rows}
    by_id.update({c.id: c for c in lex_rows})
    if not by_id:
        return []

    fused = _rrf([
        ([c.id for c in vec_rows], 1.0),
        ([c.id for c in lex_rows], _LEX_WEIGHT),
    ])
    ranked_ids = sorted(fused, key=lambda cid: -fused[cid])
    shortlist = [by_id[cid] for cid in ranked_ids[:n_rerank_top]]

    t3 = time.perf_counter()
    relevance = await rerank_scores(
        normalize_fa(query), [c.text for c in shortlist], enabled=rerank, model=rerank_model
    )
    if trace is not None:
        trace["rerank_ms"] = (time.perf_counter() - t3) * 1000
        trace["pairs_scored"] = len(shortlist) if relevance is not None else 0

    if relevance is not None:
        order = sorted(range(len(shortlist)), key=lambda i: -relevance[i])
        return [(shortlist[i], 1.0 - relevance[i]) for i in order[:top_k]]

    # rerank disabled — hand back the fused order, normalised so 1 - distance
    # is a sensible 0..1 score.
    top = max(fused.values())
    return [(by_id[cid], 1.0 - fused[cid] / top) for cid in ranked_ids[:top_k]]

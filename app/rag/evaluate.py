"""
Retrieval eval, shared by `scripts/eval.py` and the `POST /eval` endpoint.

An eval file is JSONL, one case per line:
    {"q": "...", "expect": ["source-substring", ...], "kind": "topical"}

A case "hits at rank r" if a retrieved chunk's source contains any `expect`
substring. Metrics: hit@1 / hit@3 / hit@k, MRR, and cov@k (mean fraction of
expected docs found, for multi-doc cases).
"""

import json
import pathlib

from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.base import LLMProvider
from app.rag.pipeline import answer_question
from app.rag.retriever import retrieve_scored

DEFAULT_EVAL = pathlib.Path("eval/farsi.jsonl")


def load_cases(path: pathlib.Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _first_rank(sources: list[str], expect: list[str]) -> int | None:
    for i, src in enumerate(sources):
        if any(e in src for e in expect):
            return i + 1
    return None


def _coverage(sources: list[str], expect: list[str]) -> float:
    found = {e for e in expect if any(e in s for s in sources)}
    return len(found) / len(expect) if expect else 0.0


async def run_eval(
    session: AsyncSession,
    cases: list[dict],
    *,
    top_k: int = 5,
    llm: LLMProvider | None = None,
    collection: str | None = None,
    retrieval: dict | None = None,
) -> dict:
    """`retrieval` overrides the retrieval stage for this run (hybrid, rerank,
    candidates, rerank_top, rerank_model) — that is how a sweep prices one
    setting against the score it buys, without an .env edit and a restart."""
    rows = []
    hits1 = hits3 = hitsk = 0
    rr_sum = cov_sum = 0.0
    cov_n = 0

    for case in cases:
        q, expect = case["q"], case["expect"]
        scored = await retrieve_scored(
            session, q, top_k=top_k, collection=collection, **(retrieval or {})
        )
        sources = [c.document.source for c, _ in scored]
        rank = _first_rank(sources, expect)

        rr_sum += (1.0 / rank) if rank else 0.0
        hits1 += rank == 1
        hits3 += bool(rank and rank <= 3)
        hitsk += bool(rank)

        row = {
            "q": q,
            "kind": case.get("kind", ""),
            "rank": rank,
            "hit": bool(rank),
            "retrieved": [
                {"source": c.document.source, "similarity": round(1.0 - d, 3)}
                for c, d in scored
            ],
        }
        if len(expect) > 1:
            cov = _coverage(sources, expect)
            cov_sum += cov
            cov_n += 1
            row["coverage"] = round(cov, 2)
        if llm is not None:
            res = await answer_question(session, llm, q, top_k=top_k, collection=collection)
            row["answer"] = res.answer
        rows.append(row)

    n = len(cases) or 1
    return {
        "top_k": top_k,
        "n": len(cases),
        "metrics": {
            "hit@1": round(hits1 / n, 3),
            "hit@3": round(hits3 / n, 3),
            f"hit@{top_k}": round(hitsk / n, 3),
            "MRR": round(rr_sum / n, 3),
            **({f"cov@{top_k}": round(cov_sum / cov_n, 3)} if cov_n else {}),
        },
        "cases": rows,
    }

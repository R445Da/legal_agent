"""
Side-by-side model comparison.

Extracted from the `/bench` route so the FastAPI API and the Streamlit UI run
exactly the same benchmark rather than two drifting copies.

Retrieval happens once per question and the resulting prompt is reused across
every model, so the grid isolates the generation step — the only thing that
varies between cells is the LLM.
"""

import asyncio

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Chunk
from app.llm import registry
from app.rag.pipeline import SYSTEM_PROMPT, build_prompt
from app.rag.retriever import retrieve_scored


class NothingIndexed(RuntimeError):
    """Raised when the corpus is empty — a benchmark would compare nothing."""


async def generate_cell(model_id: str, llm, prompt: str, *, max_tokens: int = 1536, **knobs) -> dict:
    """One (question, model) cell. Any provider failure becomes an `error`
    string so one broken model doesn't sink the whole grid."""
    if not llm.is_available():
        return {"model_id": model_id, "error": "provider unavailable (missing key or endpoint down)"}
    try:
        r = await llm.generate(prompt, system=SYSTEM_PROMPT, max_tokens=max_tokens, **knobs)
    except Exception as exc:  # noqa: BLE001 — surface every provider error in the grid
        return {"model_id": model_id, "error": f"{type(exc).__name__}: {exc}"[:300]}
    return {
        "model_id": model_id,
        "model": r.model,
        "answer": r.text,
        "reasoning": r.reasoning,
        "latency_ms": round(r.latency_ms) if r.latency_ms is not None else None,
        "input_tokens": r.input_tokens,
        "output_tokens": r.output_tokens,
    }


async def run_bench(
    session: AsyncSession,
    questions: list[str],
    model_ids: list[str],
    *,
    top_k: int = 5,
    max_tokens: int = 1536,
    retrieval: dict | None = None,
    **knobs,
) -> dict:
    """The question × model grid plus a per-model summary.

    `**knobs` is applied to every model that accepts it; providers ignore knobs
    they don't support, so a mixed grid (a reasoning model beside a plain chat
    model) is fine.
    """
    questions = [q.strip() for q in questions if q.strip()]
    if not questions:
        raise ValueError("No non-empty questions.")

    providers = [(mid, registry.resolve(mid)) for mid in model_ids]

    # Local models share one machine/GPU — running them concurrently just makes
    # them queue and time out, so benchmark them one at a time. Cloud models
    # (independent endpoints) run in parallel per question.
    remote = [(mid, llm) for mid, llm in providers if llm.name != "local"]
    local = [(mid, llm) for mid, llm in providers if llm.name == "local"]

    async def _cells_for(prompt: str) -> dict:
        results: dict[str, dict] = {}
        remote_task = asyncio.gather(
            *(generate_cell(mid, llm, prompt, max_tokens=max_tokens, **knobs) for mid, llm in remote)
        )
        for mid, llm in local:
            results[mid] = await generate_cell(mid, llm, prompt, max_tokens=max_tokens, **knobs)
        for cell in await remote_task:
            results[cell["model_id"]] = cell
        return results

    if not await session.scalar(select(func.count()).select_from(Chunk)):
        raise NothingIndexed("No documents indexed yet.")

    rows = []
    for q in questions:
        scored = await retrieve_scored(session, q, top_k=top_k, **(retrieval or {}))
        prompt = build_prompt(q, [c for c, _ in scored])
        by_id = await _cells_for(prompt)
        rows.append({
            "question": q,
            "cells": [by_id[mid] for mid, _ in providers],
            "contexts": [
                {
                    "n": i + 1,
                    "source": c.document.source,
                    "title": c.document.title or c.document.source,
                    "similarity": round(1.0 - d, 3),
                }
                for i, (c, d) in enumerate(scored)
            ],
        })

    summary = []
    for mid, _ in providers:
        cells = [c for r in rows for c in r["cells"] if c["model_id"] == mid]
        lat = [c["latency_ms"] for c in cells if c.get("latency_ms") is not None]
        out_tok = [c["output_tokens"] for c in cells if c.get("output_tokens") is not None]
        summary.append({
            "model_id": mid,
            "n": len(cells),
            "errors": sum(1 for c in cells if c.get("error")),
            "avg_latency_ms": round(sum(lat) / len(lat)) if lat else None,
            "avg_output_tokens": round(sum(out_tok) / len(out_tok)) if out_tok else None,
        })

    return {"top_k": top_k, "rows": rows, "summary": summary}

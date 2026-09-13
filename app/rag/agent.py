"""
The «پژوهش عاملی» route: the model researches the archive with the read-only
tools (`app/rag/tools.py`) instead of receiving one fixed retrieval.

Where the law / cases / query routes retrieve first and generate once, this
route lets the model decide what to look up — statutes, the case table,
similar cases, an entity's history, the graph — over a few rounds, then
answers from the numbered evidence the ledger collected. The result carries
the same `provenance` block as every other route, so the citation check and
the persisted `assistant_answers` row do not care which route produced it.

Never auto-routed: a demo should choose it on purpose (the «نوع پیام»
selector, `intent="agent"` on `/assistant`, or `AGENT_FOR_QUERY=1`).
"""

import time

from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.base import LLMProvider
from app.rag import provenance as prov
from app.rag.tools import EvidenceLedger, ToolLoopResult, iter_with_tools

# "archive research agent" is also the sentinel the offline mock keys on.
AGENT_SYSTEM = (
    "You are the archive research agent of a Persian insurance-law case archive. "
    "You answer only by calling the read-only tools — statute search (search_law), "
    "the case table (search_cases, similar_cases), people and companies "
    "(entity_profile), a case's graph (case_graph, graph_expand), entries and "
    "documents — never from memory. Every tool result lists numbered evidence "
    "like [1], [2]; cite those numbers, exactly as given, for every factual claim. "
    "Use several tools in one turn when they are independent. Prefer "
    "similar_cases and search_cases for precedent questions, search_law for what "
    "a statute says, entity_profile for a person or an insurer. When the "
    "evidence does not settle the question, say so plainly. Reply in Persian: "
    "a short answer, the supporting evidence with [n], then one line «جمع‌بندی»."
)


def steps_from(result: ToolLoopResult, retrieve_ms: int) -> list[dict]:
    steps = [{"name": "عامل پژوهش", "detail": f"{result.rounds} دور · {len(result.tool_log)} فراخوانی ابزار "
                                              f"· {len(result.evidence)} شاهد · حلقهٔ {result.mode}", "ms": retrieve_ms}]
    for row in result.tool_log:
        steps.append({"name": f"ابزار {row['tool']}", "detail": row["summary"], "ms": row.get("ms")})
    return steps


async def answer_with_tools(
    session: AsyncSession, llm: LLMProvider, question: str, *,
    max_rounds: int = 4, max_tokens: int = 1400, source: str = "api", persist: bool = True,
) -> dict:
    """Run the loop to completion and return the answer with its provenance."""
    t0 = time.perf_counter()
    ledger = EvidenceLedger()
    result: ToolLoopResult | None = None
    async for event in iter_with_tools(
        llm, session, f"Question: {question}", system=AGENT_SYSTEM,
        max_rounds=max_rounds, max_tokens=max_tokens, ledger=ledger,
    ):
        if event["type"] == "done":
            result = event["result"]
    assert result is not None
    total_ms = round((time.perf_counter() - t0) * 1000)

    block = prov.build_provenance(
        intent="agent", provider=getattr(llm, "name", None), model=result.model,
        evidence=result.evidence, tool_trail=result.tool_log, usage=result.usage,
        answer=result.text, latency_ms=total_ms, extra={"loop": result.mode, "rounds": result.rounds},
    )
    answer_id = None
    if persist:
        answer_id = await prov.persist_answer(
            session, intent="agent", question=question, answer=result.text,
            provenance=block, model=result.model, source=source,
        )
    # The last proposal the loop produced, if any. It is returned beside the
    # answer rather than applied: `propose_edit` writes nothing, and only the
    # confirmation step in the chat calls `entryedit.apply`.
    pending_edit = next(
        (row["proposal"] for row in reversed(result.tool_log) if row.get("proposal")), None)

    return {
        "answer": result.text,
        "pending_edit": pending_edit,
        "evidence": result.evidence,
        "tool_log": result.tool_log,
        "model": result.model,
        "reasoning": result.reasoning,
        "latency_ms": total_ms,
        "usage": result.usage,
        "steps": steps_from(result, total_ms),
        "provenance": block,
        "answer_id": answer_id,
    }

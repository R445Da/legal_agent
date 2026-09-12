import time
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.base import LLMProvider
from app.rag.retriever import effective_config, retrieve_scored

SYSTEM_PROMPT = (
    "You are a legal research assistant. Answer using only the provided "
    "excerpts. Cite the excerpt number in brackets like [1] for every claim. "
    "If the excerpts don't support an answer, say so explicitly. "
    "Reply in the same language as the question — if the question is in "
    "Persian/Farsi, answer in Persian."
)


@dataclass
class RAGAnswer:
    answer: str
    sources: list[str]
    model: str
    latency_ms: float | None
    contexts: list[dict]  # the retrieved excerpts, in citation order ([1], [2], ...)
    input_tokens: int | None = None
    output_tokens: int | None = None
    steps: list[dict] = field(default_factory=list)  # [{name, detail, ms}] pipeline trace
    reasoning: str | None = None  # chain-of-thought, when the model returns one
    retrieval: dict = field(default_factory=dict)  # per-stage ms from retrieve_scored


def snippet(text: str, terms, *, width: int = 260) -> str:
    """The passage around the first matching term, so an excerpt shows *why* it
    matched. Without it a record matched on its body was shown by title and
    summary alone, and the evidence for the match was invisible."""
    body = (text or "").strip()
    if not body:
        return ""
    for term in terms or []:
        at = body.find(term)
        if at >= 0:
            start = max(0, at - width // 2)
            end = min(len(body), at + len(term) + width // 2)
            return ("…" if start else "") + body[start:end].strip() + ("…" if end < len(body) else "")
    return body[:width].strip() + ("…" if len(body) > width else "")


def format_source(*, kind: str, title: str, body: str, meta: str = "") -> str:
    """One shape for every piece of evidence, whatever it came from.

    A document chunk and a structured entry are both just a source with an
    origin, a title and a body, so they are rendered identically and numbered in
    one sequence. That is what lets the model cite them the same way — and it is
    why `build_prompt` accepts plain strings as well as Chunk objects.
    """
    head = f"({kind}) {title}".strip()
    parts = [head, body.strip()]
    if meta:
        parts.insert(1, meta.strip())
    return "\n".join(part for part in parts if part)


def build_prompt(question: str, chunks) -> str:
    """Number every piece of evidence into one [1]..[n] sequence.

    Accepts Chunk objects or plain strings, because the assistant also feeds in
    structured `Entry` records. They must share this numbering: SYSTEM_PROMPT
    tells the model to answer only from the numbered excerpts, so evidence
    passed outside it is ignored by design.
    """
    context = "\n\n".join(
        f"[{i+1}] {c if isinstance(c, str) else c.text}" for i, c in enumerate(chunks)
    )
    return (
        f"Case excerpts:\n{context}\n\n"
        f"Question: {question}\n\n"
        "Answer, citing excerpt numbers in brackets like [1]."
    )


async def answer_question(
    session: AsyncSession,
    llm: LLMProvider,
    question: str,
    top_k: int = 5,
    collection: str | None = None,
    filters: dict | None = None,
    *,
    retrieval: dict | None = None,
    max_tokens: int = 1024,
    **knobs,
) -> RAGAnswer:
    """`retrieval` carries per-call overrides for the retrieval stage (hybrid,
    rerank, candidates, rerank_top, rerank_model); `**knobs` carries model
    tuning discovered from `app.llm.knobs` (reasoning_effort, temperature).
    Both default to the env configuration, so existing callers are unaffected.
    """
    retrieval = retrieval or {}
    steps: list[dict] = []
    cfg = effective_config(
        hybrid=retrieval.get("hybrid"), rerank=retrieval.get("rerank")
    )

    trace: dict = {}
    t = time.perf_counter()
    scored = await retrieve_scored(
        session, question, top_k=top_k, collection=collection, filters=filters,
        trace=trace, **retrieval,
    )
    chunks = [chunk for chunk, _ in scored]
    scope = collection or "همه مجموعه‌ها"
    steps.append({
        "name": "بازیابی چندمرحله‌ای",
        "detail": (
            f"نرمال‌سازی متن → تعبیهٔ پرسش ({cfg['embedding_model'].split('/')[-1]}) "
            f"→ جستجوی برداری + متنی ({cfg['candidates_per_side']}×۲ نامزد) "
            f"→ ترکیب RRF "
            + (f"→ بازرتبه‌بندی ({cfg['rerank_model'].split('/')[-1]}) " if cfg["rerank"] else "")
            + f"→ {len(chunks)} قطعهٔ برتر · دامنه: {scope}"
        ),
        "ms": round((time.perf_counter() - t) * 1000),
    })

    prompt = build_prompt(question, chunks)
    t = time.perf_counter()
    response = await llm.generate(prompt, system=SYSTEM_PROMPT, max_tokens=max_tokens, **knobs)
    steps.append({
        "name": "تولید پاسخ مستند",
        "detail": f"مدل {response.model} · {response.output_tokens or '?'} توکن خروجی · با الزام استناد [n]",
        "ms": round((time.perf_counter() - t) * 1000),
    })

    contexts = [
        {
            "n": i + 1,
            "document_id": str(chunk.document_id),
            "chunk_id": str(chunk.id),
            "title": chunk.document.title or chunk.document.source,
            "source": chunk.document.source,
            "chunk_index": chunk.chunk_index,
            "similarity": round(1.0 - distance, 3),  # cosine similarity in [-1, 1]
            "text": chunk.text,
        }
        for i, (chunk, distance) in enumerate(scored)
    ]

    return RAGAnswer(
        answer=response.text,
        sources=[str(c.document_id) for c in chunks],
        model=response.model,
        latency_ms=response.latency_ms,
        contexts=contexts,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        steps=steps,
        reasoning=response.reasoning,
        retrieval=trace,
    )

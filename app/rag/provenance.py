"""
Provenance: what an answer rests on, checked rather than trusted.

Every answer path numbers its evidence `[1]..[n]` and tells the model to cite.
That instruction is all the grounding the system used to have. This module
closes the loop with plain code: parse the bracket numbers the model actually
wrote, check each one names a real piece of evidence, split the answer into
claims and mark the ones that carry no valid citation. The result — evidence,
tool trail, grounding verdict, token usage — is one `provenance` block that
rides on the API response, the chat message, and a row in `assistant_answers`.

Deterministic on purpose: the same answer and evidence always verify the same
way, so the offline `mock` model and CI see exactly what a real model would.
"""

import datetime as dt
import re
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

PROVENANCE_VERSION = 1

_FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
_CITE_RX = re.compile(r"\[\s*([0-9۰-۹]{1,3})\s*\]")
# A claim ends at a sentence mark (Latin or Persian) or a line break.
_SENTENCE_END = re.compile(r"(?<=[.!?؟؛])\s+|\n+")
_MIN_CLAIM_CHARS = 25

_KIND_FA = {"law": "ماده", "case": "پرونده", "entry": "مدخل", "document": "سند", "chunk": "قطعه"}


def _digits(value: str) -> str:
    return (value or "").translate(_FA_DIGITS)


def cited_numbers(text: str) -> list[int]:
    """Every `[n]` in the text, in order of first appearance, without repeats."""
    seen: list[int] = []
    for match in _CITE_RX.finditer(text or ""):
        n = int(_digits(match.group(1)))
        if n not in seen:
            seen.append(n)
    return seen


def _sentences(text: str):
    """(sentence, (start, end)) pairs, offsets into the original text."""
    pos = 0
    for match in _SENTENCE_END.finditer(text):
        chunk = text[pos:match.start()]
        if chunk.strip():
            yield chunk, (pos, match.start())
        pos = match.end()
    tail = text[pos:]
    if tail.strip():
        yield tail, (pos, len(text))


def verify_citations(answer: str, evidence: list[dict]) -> dict:
    """Check the `[n]` citations in `answer` against the numbered `evidence`.

    Returns `{cited, valid, invalid, coverage, claims, status}` where `claims`
    are the answer's sentences (headings and fragments skipped) each with the
    citations it carries and whether one of them is real, `coverage` is the
    share of claims that are supported, and `status` is `ok` (everything cited,
    nothing dangling), `partial`, or `unsupported`.
    """
    known = {int(item["n"]) for item in evidence or [] if item.get("n") is not None}
    cited = cited_numbers(answer)
    valid = [n for n in cited if n in known]
    invalid = [n for n in cited if n not in known]

    claims: list[dict] = []
    for sentence, span in _sentences(answer or ""):
        text = sentence.strip()
        if len(text) < _MIN_CLAIM_CHARS or text.endswith((":", "：")):
            continue
        cites = cited_numbers(sentence)
        claims.append({
            "text": text, "span": list(span), "cites": cites,
            "supported": any(n in known for n in cites),
        })

    supported = sum(1 for c in claims if c["supported"])
    if claims:
        coverage = round(supported / len(claims), 3)
    else:
        coverage = 1.0 if valid else 0.0

    if not known or (not valid and not claims):
        status = "unsupported"
    elif coverage >= 0.8 and not invalid:
        status = "ok"
    elif valid:
        status = "partial"
    else:
        status = "unsupported"

    return {
        "cited": cited, "valid": valid, "invalid": invalid, "coverage": coverage,
        "claims": claims, "status": status,
        "unsupported_claims": [{"text": c["text"], "span": c["span"]} for c in claims if not c["supported"]],
    }


# --------------------------------------------------------------------------- #
# Evidence from the three existing answer paths
# --------------------------------------------------------------------------- #
def evidence_from_refs(refs: list[dict]) -> list[dict]:
    """Law articles as `lawbase.answer_law_question` numbers them."""
    return [
        {"n": i, "kind": "law", "id": str(r.get("id")), "cite": r.get("cite"),
         "title": r.get("title") or r.get("cite"), "score": None,
         "text": (r.get("text") or "")[:400]}
        for i, r in enumerate(refs or [], 1)
    ]


def evidence_from_cases(cases: list[dict], *, offset: int = 0) -> list[dict]:
    """Case records as `casebase.answer_case_question` numbers them; `offset`
    continues an existing sequence (the similar-case stage after the articles)."""
    return [
        {"n": i, "kind": "case", "id": str(c.get("id")), "cite": c.get("case_number"),
         "case_number": c.get("case_number"), "title": c.get("title"),
         "score": c.get("score"), "text": (c.get("outcome") or c.get("summary") or "")[:400],
         **({"why": c["why"]} if c.get("why") else {})}
        for i, c in enumerate(cases or [], offset + 1)
    ]


def evidence_from_contexts(contexts: list[dict]) -> list[dict]:
    """Retrieved excerpts (and spliced-in entries) as the chat/API number them."""
    out = []
    for c in contexts or []:
        source = str(c.get("source") or "")
        kind = "entry" if source.startswith("entry/") else "chunk"
        out.append({
            "n": c.get("n"), "kind": kind,
            "id": str(c.get("chunk_id") or c.get("document_id") or source),
            "cite": c.get("title"), "title": c.get("title") or source,
            "score": c.get("similarity"), "document_id": c.get("document_id"),
            "text": (c.get("text") or "")[:400],
        })
    return out


def evidence_label(item: dict) -> str:
    """«ماده ۳۰ قانون بیمه» / «پروندهٔ ۱۴۰۲…» — the short human form."""
    kind = _KIND_FA.get(item.get("kind", ""), item.get("kind", ""))
    name = item.get("cite") or item.get("title") or item.get("id", "")
    return f"{kind}: {name}" if kind else str(name)


# --------------------------------------------------------------------------- #
# The block
# --------------------------------------------------------------------------- #
def build_provenance(
    *, intent: str, provider: str | None, model: str | None, evidence: list[dict],
    tool_trail: list[dict] | None = None, usage: dict | None = None,
    grounding: dict | None = None, answer: str | None = None,
    latency_ms: float | None = None, extra: dict | None = None,
) -> dict:
    if grounding is None:
        grounding = verify_citations(answer or "", evidence)
    slim = {k: v for k, v in grounding.items() if k != "claims"}
    return {
        "version": PROVENANCE_VERSION,
        "intent": intent,
        "provider": provider,
        "model": model,
        "evidence": [
            {k: v for k, v in item.items() if k != "text"} | {"label": evidence_label(item)}
            for item in evidence
        ],
        "tool_trail": list(tool_trail or []),
        "grounding": slim,
        "usage": dict(usage or {}),
        "latency_ms": round(latency_ms) if latency_ms else None,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        **(extra or {}),
    }


async def persist_answer(
    session: AsyncSession, *, intent: str, question: str, answer: str,
    provenance: dict, model: str | None = None, run_id=None, source: str = "api",
) -> str:
    """One `assistant_answers` row per answered question. Commits."""
    from app.db.models import AssistantAnswer

    from app.rag import hooks

    row = AssistantAnswer(
        source=source, intent=intent, question=question, answer=answer or "",
        model=model, provenance=provenance,
        run_id=uuid.UUID(str(run_id)) if run_id else None,
    )
    session.add(row)
    await session.flush()
    grounding = (provenance or {}).get("grounding") or {}
    queued = await hooks.emit(session, "answer.created", {
        "answer_id": str(row.id), "intent": intent, "source": source, "model": model,
        "question": (question or "")[:300], "grounding_status": grounding.get("status"),
        "coverage": grounding.get("coverage"), "evidence": len((provenance or {}).get("evidence") or []),
        "tool_calls": len((provenance or {}).get("tool_trail") or []),
    })
    await session.commit()
    await session.refresh(row)
    if queued:
        hooks.drain_soon(session)
    return str(row.id)


def answer_view(row) -> dict:
    return {
        "id": str(row.id), "created_at": row.created_at.isoformat() if row.created_at else None,
        "source": row.source, "intent": row.intent, "question": row.question,
        "answer": row.answer, "model": row.model,
        "run_id": str(row.run_id) if row.run_id else None,
        "provenance": row.provenance or {},
    }

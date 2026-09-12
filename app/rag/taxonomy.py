"""
The label taxonomy — ported from the reference mock-up — plus a label proposer.

Section ۰۸ طبقه‌بندی renders the seed tree; the pipeline's labels gate proposes a
set for a draft and the user edits it. The proposer is one small LLM call with a
deterministic keyword fallback, so it still returns something useful when a
local model hands back nothing parseable.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Entry

# (root, [(category, [leaf, ...])]) — the "طبقه‌بندی سلسله‌مراتبی" from app.html.
TAXONOMY = [
    {"root": "حقوقی", "categories": [
        {"name": "ملک", "leaves": ["تخلیه", "مالکیت", "سند", "اجاره"]},
        {"name": "قرارداد", "leaves": ["نقض قرارداد", "فسخ", "مطالبه وجه"]},
        {"name": "خانواده", "leaves": ["طلاق", "مهریه", "حضانت", "نفقه"]},
    ]},
    {"root": "کیفری", "categories": [
        {"name": "جرائم مالی", "leaves": ["کلاهبرداری", "خیانت در امانت", "اختلاس"]},
        {"name": "جرائم علیه اموال", "leaves": ["سرقت", "تخریب"]},
        {"name": "جرائم علیه اشخاص", "leaves": ["ضرب و جرح", "توهین", "تهدید"]},
    ]},
]


def leaves() -> list[str]:
    return [leaf for root in TAXONOMY for cat in root["categories"] for leaf in cat["leaves"]]


def roots() -> list[str]:
    return [root["root"] for root in TAXONOMY]


async def corpus_tags(session: AsyncSession, *, limit: int = 40) -> list[str]:
    """Tags already in the archive — real precedent for what to propose."""
    rows = (await session.execute(select(Entry.tags))).scalars().all()
    counts: dict[str, int] = {}
    for tags in rows:
        for tag in tags or []:
            tag = str(tag).strip()
            if tag:
                counts[tag] = counts.get(tag, 0) + 1
    return [tag for tag, _ in sorted(counts.items(), key=lambda kv: -kv[1])[:limit]]


_SYSTEM = (
    "You label a Persian legal record with 2-4 short SUBJECT-MATTER category "
    "labels (the area of law and the specific claim/charge). Prefer labels from "
    "the provided vocabulary; add a new one only if nothing fits. Do NOT use "
    "procedural or structural words like پرونده، دادگاه، شاکی، متهم، خواهان، "
    "لایحه، جلسه، صورت‌جلسه. Reply with JSON only: {\"labels\": [\"...\"]}"
)

# Procedural / structural words that describe every record, not its subject.
_STOP = {
    "پرونده", "دادگاه", "شاکی", "متهم", "خواهان", "خوانده", "لایحه",
    "لایحه دفاعیه", "جلسه", "صورت‌جلسه", "صورتجلسه", "دادخواست", "رأی", "رای",
    "قاضی", "وکیل", "دادنامه", "کیفرخواست", "شعبه", "یادداشت",
    "کلاسه", "کلاسه فوق", "فوق", "موصوف", "مطروحه", "تقدیم", "استحضار",
    "احتراماً", "دفاعیه", "دفاعیات", "رسیدگی", "ختم رسیدگی", "اتهام", "اتهامی",
}


async def propose_labels(llm, draft: dict, session: AsyncSession) -> list[str]:
    vocab = list(dict.fromkeys(
        t for t in [*leaves(), *roots(), *(await corpus_tags(session))]
        if t not in _STOP
    ))
    entities = draft.get("entities") or {}
    subject = " / ".join(
        str(x) for x in (
            draft.get("title"), entities.get("topic"),
            entities.get("court"), draft.get("summary"),
        ) if x
    )
    labels: list[str] = []
    try:
        from app.rag.orchestrator import _parse_json

        resp = await llm.generate(
            f"Vocabulary: {', '.join(vocab)}\n\nRecord: {subject}",
            system=_SYSTEM, max_tokens=200, json_mode=True, reasoning_effort="low",
        )
        got = _parse_json(resp.text).get("labels")
        if isinstance(got, list):
            labels = [str(x).strip() for x in got if str(x).strip()]
    except Exception:  # noqa: BLE001 — the fallback covers a bad/empty response
        labels = []

    if not labels:
        labels = [term for term in vocab if term and term in (subject or "")][:5]

    return _clean(labels, vocab)[:5]


def _clean(labels: list[str], vocab: list[str]) -> list[str]:
    """A label is a category, not a sentence: drop stop words, phrases that
    merely contain one, and anything longer than three words. Keep known-vocab
    terms even if long (e.g. «نقض حق مؤلف نرم‌افزار»)."""
    vocab_set = set(vocab)
    out: list[str] = []
    for label in dict.fromkeys(str(x).strip() for x in labels):
        if not label or label in _STOP:
            continue
        if label in vocab_set:
            out.append(label)
            continue
        if any(stop in label.split() for stop in _STOP):
            continue
        if len(label.split()) > 3:
            continue
        out.append(label)
    return out

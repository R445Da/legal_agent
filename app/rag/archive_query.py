"""
«پرسش از آرشیو» — ask the archive about itself.

Not retrieval. Retrieval finds passages that look like a question; this answers
questions *about the shape of the collection*: how many kinds of driving-offence
case there are, which labels dominate third-party motor claims, how many of the
ones just counted are still open. The archive already knows all of it — every
case carries tags, an insurance line, a case type, a status and an outcome — so
the answer is arithmetic over rows, never a guess.

The split of labour is the project's standing rule, applied to a step that
genuinely needs judgement:

    the model  chooses *which labels the question is about*, from the real
               vocabulary, and returns names only — never a number
    this file  does everything else in SQL: which cases carry those labels,
               how many, grouped how

That division exists because of a single example. Asked about «تخلفات رانندگی»,
substring matching pulls in «مستمری» — a pension, nine cases — because it
contains «مست». Embedding similarity makes the same mistake for the same
reason: the two strings look alike. Only something that knows what the words
*mean* keeps them apart, and that is the one thing a model is better at than a
query. So it is asked exactly that and nothing more, and whatever it returns is
intersected with the real vocabulary before a single row is counted — a label
the model invents cannot reach the arithmetic.

A question spans vocabularies, and how they combine is the difference between
a right and a wrong number. «پرونده‌های تقلب بیمه‌ای در رشتهٔ آتش‌سوزی» names a
tag group *and* a line and means the cases that are both, so vocabularies
intersect; several driving tags in one question are alternatives, so labels
within a vocabulary unite. Unioning everything answered that question with
twenty-five cases — every fraud case plus every fire case — which the eval
caught.

Follow-ups refine rather than re-search. `resolve()` takes `within=` — the case
ids from the previous answer — so «از همان‌ها چند تا مختومه شده؟» filters the
seventeen cases already on screen instead of quietly answering about a different
set. Status and outcome are refinements, not search vocabularies: nobody asks
"which cases are about مختومه", they ask how many of *these* are.
"""

from __future__ import annotations

import json
import re
import time

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Entry, LegalCase
from app.llm.base import LLMProvider
from app.rag.casebase import STATUS_FA, case_dict

# How much of the vocabulary the model is shown. The archive has a few hundred
# labels; all of them fit comfortably, and showing all of them is the point —
# it can only choose names that exist.
_MAX_VOCAB = 400


async def vocabulary(session: AsyncSession) -> dict:
    """Every label the archive actually uses, with how many cases carry it."""
    tags: dict[str, int] = {}
    rows = (await session.execute(
        select(Entry.tags, Entry.case_id).where(Entry.case_id.isnot(None))
    )).all()
    seen: dict[str, set] = {}
    for values, case_id in rows:
        for value in values or []:
            name = str(value).strip()
            if name:
                seen.setdefault(name, set()).add(str(case_id))
    tags = {name: len(cases) for name, cases in seen.items()}

    async def _counts(column):
        result = (await session.execute(
            select(column, func.count()).where(column.isnot(None)).group_by(column)
        )).all()
        return {str(v): n for v, n in result if str(v).strip()}

    return {
        "tags": dict(sorted(tags.items(), key=lambda kv: -kv[1])[:_MAX_VOCAB]),
        "insurance_lines": await _counts(LegalCase.insurance_line),
        "case_types": await _counts(LegalCase.case_type),
    }


_SYSTEM = (
    "You choose which labels of a Persian legal-insurance archive a question is "
    "about. You are given the archive's real vocabulary in three groups and a "
    "question. Reply with JSON only: "
    '{"tags": [...], "insurance_lines": [...], "case_types": [...], "reason": "..."}. '
    "Copy names EXACTLY as given — never invent, translate or reword one, and "
    "never return a name that is not in the lists. Choose every label the "
    "question genuinely covers and nothing else: a label that merely looks "
    "similar is wrong. For example «مستمری» (a pension) must not be chosen for a "
    "question about drunk driving just because it contains the letters «مست». "
    "Return no counts and no case numbers. If nothing fits, return empty lists."
)


def _prompt(question: str, vocab: dict) -> str:
    def block(title: str, items: dict) -> str:
        return f"{title}:\n" + "\n".join(f"- {name} ({n})" for name, n in items.items())

    return (
        block("TAGS", vocab["tags"]) + "\n\n"
        + block("INSURANCE LINES", vocab["insurance_lines"]) + "\n\n"
        + block("CASE TYPES", vocab["case_types"]) + "\n\n"
        + f"Question: {question}\n\nRespond with JSON only."
    )


_COUNT_SUFFIX = re.compile(r"\s*[(（]\s*[0-9۰-۹]+\s*[)）]\s*$")


def _normalise(name: str) -> str:
    """Undo the two things a model does to a name it was told to copy.

    The vocabulary is shown as «شخص ثالث (34)» so the model can see how common a
    label is — and it copies the line whole, count and all. Stripping a trailing
    parenthesised number costs nothing and turns a rejected name into a usable
    one. (The eval found this: every label of one question was rejected for
    carrying its own count.)
    """
    return _COUNT_SUFFIX.sub("", str(name or "").strip()).strip()


def _kept(chosen, allowed: dict) -> tuple[list[str], list[str]]:
    """Split what the model returned into names that exist and names that do not.

    The second list is not thrown away: a model reaching for a label the archive
    does not have is worth showing, because it usually means the question is
    about something nobody has tagged yet.
    """
    keep, unknown = [], []
    for item in chosen or []:
        name = _normalise(item)
        if not name or name in keep or name in unknown:
            continue          # models repeat themselves; count each label once
        (keep if name in allowed else unknown).append(name)
    return keep, unknown


async def select_facets(llm: LLMProvider, question: str, vocab: dict) -> dict:
    """The one model call: which labels is this question about?"""
    from app.rag.orchestrator import _parse_json

    response = await llm.generate(
        _prompt(question, vocab), system=_SYSTEM, max_tokens=700,
        json_mode=True, reasoning_effort="low",
    )
    data = _parse_json(response.text) or {}

    tags, unknown_tags = _kept(data.get("tags"), vocab["tags"])
    lines, unknown_lines = _kept(data.get("insurance_lines"), vocab["insurance_lines"])
    types, unknown_types = _kept(data.get("case_types"), vocab["case_types"])
    return {
        "tags": tags, "insurance_lines": lines, "case_types": types,
        "rejected": unknown_tags + unknown_lines + unknown_types,
        "reason": str(data.get("reason") or "")[:300],
        "model": response.model,
    }


async def _cases_for(session: AsyncSession, facets: dict) -> dict[str, set]:
    """Case ids per chosen label, in SQL. Nothing here is approximate."""
    hits: dict[str, set] = {}

    for tag in facets.get("tags") or []:
        rows = (await session.execute(
            select(Entry.case_id).where(Entry.case_id.isnot(None), Entry.tags.contains([tag]))
        )).scalars().all()
        if rows:
            hits[tag] = {str(r) for r in rows}

    for column, names in ((LegalCase.insurance_line, facets.get("insurance_lines")),
                          (LegalCase.case_type, facets.get("case_types"))):
        for name in names or []:
            rows = (await session.execute(
                select(LegalCase.id).where(column == name)
            )).scalars().all()
            if rows:
                hits[name] = {str(r) for r in rows}
    return hits


# Words that mean "of the ones you just showed me", not "find me cases about".
_REFINING = ("مختومه", "جاری", "تجدیدنظر", "وضعیت", "نتیجه", "چند تا از",
             "از همان", "از همین", "از این‌ها", "از اینها", "از آن‌ها", "از آنها")


def is_refinement(question: str) -> bool:
    """Whether a question asks about the set already on screen."""
    folded = " ".join((question or "").replace("‌", " ").split())
    return any(word.replace("‌", " ") in folded for word in _REFINING)


async def _regroup(session: AsyncSession, case_ids: list[str]) -> dict:
    """The same breakdown `resolve()` produces, over a set already chosen."""
    return await _breakdown(session, {str(i) for i in case_ids}, {})


async def resolve(
    session: AsyncSession, facets: dict, *, within: list[str] | None = None,
) -> dict:
    """The cases those labels cover, and how they break down.

    `within` narrows to a previous answer's set, which is what makes a follow-up
    a refinement of what is on screen rather than a fresh question.
    """
    per_label = await _cases_for(session, facets)

    # Union inside a vocabulary, intersection across them. «پرونده‌های تقلب
    # بیمه‌ای در رشتهٔ آتش‌سوزی» names a tag group *and* a line, and means the
    # cases that are both — unioning the two answered with every fraud case
    # plus every fire case, twenty-five where the truth was far fewer. Within
    # one vocabulary the opposite holds: several driving tags are alternatives,
    # not conditions, so those are OR-ed.
    groups: list[set[str]] = []
    for key in ("tags", "insurance_lines", "case_types"):
        names = [n for n in (facets.get(key) or []) if n in per_label]
        if names:
            union: set[str] = set()
            for name in names:
                union |= per_label[name]
            groups.append(union)
    matched: set[str] = set.intersection(*groups) if groups else set()
    if within is not None:
        keep = {str(i) for i in within}
        matched &= keep
        per_label = {label: ids & keep for label, ids in per_label.items()}

    return await _breakdown(session, matched, per_label)


async def _breakdown(session: AsyncSession, matched: set, per_label: dict) -> dict:
    """Counts over a chosen set of cases. Pure arithmetic, no model, no guess."""
    if not matched:
        return {"case_ids": [], "count": 0, "by_label": [], "cases": [],
                "by_line": [], "by_type": [], "by_status": []}

    rows = (await session.execute(
        select(LegalCase).where(LegalCase.id.in_(list(matched)))
    )).scalars().all()
    cases = [case_dict(r) for r in rows]

    def group(key: str) -> list[tuple[str, int]]:
        counts: dict[str, int] = {}
        for case in cases:
            value = str(case.get(key) or "—")
            counts[value] = counts.get(value, 0) + 1
        return sorted(counts.items(), key=lambda kv: -kv[1])

    return {
        "case_ids": sorted(str(m) for m in matched),
        "count": len(matched),
        "by_label": sorted(((k, len(v & matched)) for k, v in (per_label or {}).items()
                            if v & matched), key=lambda kv: -kv[1]),
        "by_line": group("insurance_line"),
        "by_type": group("case_type"),
        "by_status": [(STATUS_FA.get(v, v), n) for v, n in group("status")],
        "cases": sorted(cases, key=lambda c: str(c.get("filed_date") or ""), reverse=True),
    }


async def run(
    session: AsyncSession, llm: LLMProvider, question: str, *,
    within: list[str] | None = None,
) -> dict:
    """The tool: a question about the archive in, a counted answer out."""
    t0 = time.perf_counter()

    # «از همان‌ها چند تا مختومه شده؟» names no label at all — it asks how the
    # set already on screen breaks down. Sending it to label selection returned
    # nothing and reported zero cases, which is the wrong answer to a question
    # whose answer was already in hand. A refinement of an existing set skips
    # the model entirely and just regroups it.
    if within is not None and is_refinement(question):
        result = await _regroup(session, list(within))
        ms = round((time.perf_counter() - t0) * 1000)
        return {**result, "question": question,
                "facets": {"tags": [], "insurance_lines": [], "case_types": [],
                           "rejected": [], "reason": "پالایش مجموعهٔ قبلی", "model": None},
                "steps": [{"name": "پالایش مجموعهٔ قبلی",
                           "detail": f"{result['count']} پرونده — بدون فراخوانی مدل",
                           "ms": ms}],
                "within": True, "refinement": True, "model": None,
                "vocabulary_size": 0}

    vocab = await vocabulary(session)
    vocab_ms = round((time.perf_counter() - t0) * 1000)

    t1 = time.perf_counter()
    facets = await select_facets(llm, question, vocab)
    pick_ms = round((time.perf_counter() - t1) * 1000)

    # The model found nothing to match but a set is in hand: regroup it rather
    # than claim the archive holds nothing.
    if within is not None and not (facets["tags"] or facets["insurance_lines"]
                                   or facets["case_types"]):
        result = await _regroup(session, list(within))
        return {**result, "question": question, "facets": facets,
                "steps": [{"name": "پالایش مجموعهٔ قبلی",
                           "detail": f"{result['count']} پرونده", "ms": pick_ms}],
                "within": True, "refinement": True, "model": facets.get("model"),
                "vocabulary_size": len(vocab["tags"])}

    t2 = time.perf_counter()
    result = await resolve(session, facets, within=within)
    sql_ms = round((time.perf_counter() - t2) * 1000)

    chosen = (facets["tags"] + facets["insurance_lines"] + facets["case_types"])
    steps = [
        {"name": "واژگان آرشیو",
         "detail": f"{len(vocab['tags'])} برچسب · {len(vocab['insurance_lines'])} رشته · "
                   f"{len(vocab['case_types'])} نوع دعوا", "ms": vocab_ms},
        {"name": "انتخاب برچسب‌های مرتبط",
         "detail": ("، ".join(chosen) or "هیچ برچسبی منطبق نشد")
                   + (f" · {len(facets['rejected'])} نام خارج از واژگان کنار گذاشته شد"
                      if facets["rejected"] else ""),
         "ms": pick_ms},
        {"name": "شمارش در پایگاه داده",
         "detail": f"{result['count']} پرونده"
                   + (" (از مجموعهٔ قبلی)" if within is not None else ""),
         "ms": sql_ms},
    ]
    return {**result, "question": question, "facets": facets, "steps": steps,
            "within": within is not None, "model": facets.get("model"),
            "vocabulary_size": len(vocab["tags"])}


def summarise(result: dict) -> str:
    """The answer in Persian, composed from the counts — no model involved."""
    from app.ui.theme import fa_num

    if not result["count"]:
        return ("هیچ پرونده‌ای با این پرسش منطبق نشد. "
                + (f"نام‌های خارج از واژگان: {'، '.join(result['facets']['rejected'])}"
                   if result["facets"].get("rejected") else
                   "شاید این موضوع هنوز در آرشیو برچسب‌گذاری نشده است."))

    chosen = result["facets"]["tags"] + result["facets"]["insurance_lines"] + result["facets"]["case_types"]

    if result.get("refinement"):
        # A refinement chose no labels: it regrouped the set already on screen,
        # so "matched 0 labels" would be nonsense.
        lines = [f"از میان {fa_num(result['count'])} پروندهٔ این مجموعه:"]
    else:
        lines = [
            ("از میان پرونده‌های این مجموعه، " if result["within"] else "")
            + f"{fa_num(result['count'])} پرونده با {fa_num(len(chosen))} برچسب منطبق شد: "
            + "، ".join(chosen) + ".",
            "",
            "بر حسب برچسب:",
        ]
        lines += [f"• {label} — {fa_num(n)} پرونده" for label, n in result["by_label"]]
    if result["by_status"]:
        lines += ["", "بر حسب وضعیت: "
                  + "، ".join(f"{v} {fa_num(n)}" for v, n in result["by_status"])]
    if len(result["by_line"]) > 1:
        lines += ["بر حسب رشتهٔ بیمه‌ای: "
                  + "، ".join(f"{v} {fa_num(n)}" for v, n in result["by_line"][:6])]
    return "\n".join(lines)


def as_json(result: dict) -> str:
    """The working set, for the tool loop to hand back to a model."""
    return json.dumps({
        "count": result["count"],
        "labels": result["facets"]["tags"] + result["facets"]["insurance_lines"]
                  + result["facets"]["case_types"],
        "by_label": result["by_label"], "by_status": result["by_status"],
    }, ensure_ascii=False)

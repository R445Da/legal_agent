"""
Similar past cases, found through the graph as well as the text.

Three legs, fused:

- **FTS** over the case table (`casebase.search_cases`) — shared words.
- **Vector** search over the documents (`retriever.retrieve_scored`), mapped
  back to the cases their entries belong to — similar text.
- **Graph** — one meet-in-the-middle query over `graph_edges`: from the seed
  cases (or straight from the cited articles) to the shared node, then back
  to every other case that touches it. Shared articles weigh most, then a
  prior SIMILAR_TO link, a shared party, a shared label, the same court; each
  divided by ln(1 + degree) so a hub (the insurer that is party to half the
  archive, a judge) does not drown the signal.

Every result carries `why` (Persian, one line per link) and `path` (the
concrete nodes and relations that connected it), so the UI can show *why* a
case is similar and the model can cite it as evidence. `outcome_lessons`
reads the outcomes with rules — what worked, what failed, what is pending —
and `stage()` is the second pass the law / cases / query routes run after
their answer: the similar cases become numbered evidence and a short
comparative paragraph («تحلیل تطبیقی») is generated over them.
"""

import math
import os
import re
import time
import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Entry, GraphEdge, LegalCase
from app.llm.base import LLMProvider
from app.rag import graph
from app.rag.graph import RELATION_FA, _labels_for

REL_W = {"CITES": 1.0, "SIMILAR_TO": 0.8, "PARTY": 0.6, "LABELED": 0.4, "HEARD_AT": 0.2}
_JUDGE_ROLES = {"ghazi"}
_RRF_K = 60

_EXPAND_SQL = text("""
WITH seed_cases AS (
    SELECT unnest(CAST(:case_ids AS text[])) AS id
),
seed_mids AS (
    SELECT t.mid_type, t.mid_id, NULL::text AS seed, NULL::text AS relation
    FROM unnest(CAST(:mid_types AS text[]), CAST(:mid_ids AS text[])) AS t(mid_type, mid_id)
),
hop1 AS (
    SELECT e.dst_type AS mid_type, e.dst_id AS mid_id, e.src_id AS seed, e.relation
    FROM graph_edges e JOIN seed_cases s ON e.src_type = 'case' AND e.src_id = s.id
    WHERE e.relation IN ('CITES', 'PARTY', 'LABELED', 'HEARD_AT')
    UNION ALL
    SELECT mid_type, mid_id, seed, relation FROM seed_mids
),
deg AS (
    SELECT g.dst_type, g.dst_id, count(*) AS n
    FROM graph_edges g
    WHERE g.src_type = 'case'
      AND (g.dst_type, g.dst_id) IN (SELECT mid_type, mid_id FROM hop1)
    GROUP BY g.dst_type, g.dst_id
)
SELECT e2.src_id AS case_id, h.seed, e2.relation, h.mid_type, h.mid_id, d.n AS degree, e2.meta
FROM hop1 h
JOIN graph_edges e2
  ON e2.src_type = 'case' AND e2.dst_type = h.mid_type AND e2.dst_id = h.mid_id
 AND (h.relation IS NULL OR e2.relation = h.relation)
JOIN deg d ON d.dst_type = h.mid_type AND d.dst_id = h.mid_id
WHERE h.seed IS NULL OR e2.src_id <> h.seed
LIMIT :max_paths
""")


def _uuid(value) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


# --------------------------------------------------------------------------- #
# Graph leg
# --------------------------------------------------------------------------- #
async def expand(
    session: AsyncSession, *, case_ids: list[str] | None = None,
    nodes: list[tuple[str, str]] | None = None, max_paths: int = 400,
) -> dict[str, dict]:
    """Cases reachable in two hops from the seeds, scored by what they share.

    `case_ids` are seed cases (their CITES / PARTY / LABELED / HEARD_AT edges
    are followed); `nodes` are shared nodes entered directly, e.g. the law
    articles an answer cited — `[("law", id), ...]`. Returns
    `{case_id: {"score", "paths": [...], "links": {...}}}` with display labels.
    """
    case_ids = [str(c) for c in (case_ids or []) if c]
    nodes = [(t, str(i)) for t, i in (nodes or []) if i]
    if not case_ids and not nodes:
        return {}
    rows = (await session.execute(_EXPAND_SQL, {
        "case_ids": case_ids, "mid_types": [t for t, _ in nodes], "mid_ids": [i for _, i in nodes],
        "max_paths": max_paths,
    })).all()

    # SIMILAR_TO is case → case, one hop from the seeds.
    similar_rows = []
    if case_ids:
        similar_rows = (await session.execute(
            select(GraphEdge).where(
                GraphEdge.relation == "SIMILAR_TO", GraphEdge.src_type == "case", GraphEdge.src_id.in_(case_ids)
            )
        )).scalars().all()

    out: dict[str, dict] = {}
    label_nodes: dict[tuple[str, str], dict] = {}

    def bucket(case_id: str) -> dict:
        return out.setdefault(case_id, {"score": 0.0, "paths": [], "links": {}})

    for row in rows:
        case_id = str(row.case_id)
        if case_id in case_ids:
            continue
        relation = row.relation
        degree = max(int(row.degree or 1), 1)
        meta = row.meta or {}
        weight = REL_W.get(relation, 0.3) / math.log(1 + degree)
        if relation == "PARTY" and meta.get("role") in _JUDGE_ROLES:
            weight *= 0.3
        b = bucket(case_id)
        key = (relation, row.mid_type, str(row.mid_id))
        if key in b["links"]:
            continue  # the same shared node reached from two seeds counts once
        b["links"][key] = {"relation": relation, "mid": {"type": row.mid_type, "id": str(row.mid_id)},
                           "seed": str(row.seed) if row.seed else None, "degree": degree, "meta": meta,
                           "weight": round(weight, 3)}
        b["score"] += weight
        label_nodes.setdefault((row.mid_type, str(row.mid_id)), {"type": row.mid_type, "id": str(row.mid_id)})
        label_nodes.setdefault(("case", case_id), {"type": "case", "id": case_id})
        if row.seed:
            label_nodes.setdefault(("case", str(row.seed)), {"type": "case", "id": str(row.seed)})

    for edge in similar_rows:
        case_id = str(edge.dst_id)
        if case_id in case_ids:
            continue
        b = bucket(case_id)
        key = ("SIMILAR_TO", "case", str(edge.src_id))
        if key in b["links"]:
            continue
        weight = REL_W["SIMILAR_TO"] * float(edge.weight or 1.0)
        b["links"][key] = {"relation": "SIMILAR_TO", "mid": None, "seed": str(edge.src_id), "degree": 1,
                           "meta": edge.meta or {}, "weight": round(weight, 3)}
        b["score"] += weight
        label_nodes.setdefault(("case", case_id), {"type": "case", "id": case_id})
        label_nodes.setdefault(("case", str(edge.src_id)), {"type": "case", "id": str(edge.src_id)})

    if label_nodes:
        await _labels_for(session, label_nodes)

    for case_id, b in out.items():
        for link in b["links"].values():
            seed = link["seed"]
            path = []
            rel = {"relation": link["relation"], "relation_fa": RELATION_FA.get(link["relation"], link["relation"])}
            if link["mid"]:
                mid = link["mid"]
                mid_label = label_nodes[(mid["type"], mid["id"])].get("label", "")
                if seed:
                    # seed case —rel→ shared node ←rel— candidate case
                    path.append({"type": "case", "id": seed, "label": label_nodes[("case", seed)].get("label", "")})
                    path.append(rel)
                path.append({**mid, "label": mid_label})
                path.append({**rel, "dir": "in"})
                link["why"] = _why(link["relation"], mid["type"], mid_label, link["meta"])
            else:
                path.append({"type": "case", "id": seed, "label": label_nodes[("case", seed)].get("label", "")})
                path.append({"relation": "SIMILAR_TO", "relation_fa": RELATION_FA["SIMILAR_TO"]})
                link["why"] = "قبلاً به‌عنوان پروندهٔ مشابه پیوند خورده است"
            path.append({"type": "case", "id": case_id, "label": label_nodes[("case", case_id)].get("label", "")})
            link["path"] = path
        b["paths"] = [link["path"] for link in b["links"].values()]
        b["why"] = [link["why"] for link in b["links"].values()]
        b["label"] = label_nodes.get(("case", case_id), {}).get("label", "")
        b["links"] = list(b["links"].values())
        b["score"] = round(b["score"], 3)
    return out


def _why(relation: str, mid_type: str, label: str, meta: dict) -> str:
    if relation == "CITES":
        return f"استناد مشترک به {label}"
    if relation == "PARTY":
        role = (meta or {}).get("role_fa")
        return f"طرف مشترک: {label}" + (f" ({role})" if role else "")
    if relation == "HEARD_AT":
        return f"همان مرجع رسیدگی: {label}"
    if relation == "LABELED":
        return f"برچسب مشترک: {label}"
    return f"{RELATION_FA.get(relation, relation)}: {label}"


async def expand_for_tool(session: AsyncSession, node_type: str, node_id: str, *, depth: int = 2) -> dict:
    """The `graph_expand` model tool: cases connected to a node, with reasons."""
    from app.rag.casebase import get_case

    if node_type == "case":
        case = await get_case(session, node_id)
        if not case:
            return {"error": "پرونده یافت نشد"}
        found = await expand(session, case_ids=[case["id"]])
    elif node_type == "law":
        found = await expand(session, nodes=[("law", node_id)])
    else:
        found = await expand(session, nodes=[(node_type, node_id)])
    ranked = sorted(found.items(), key=lambda kv: -kv[1]["score"])[:10]
    cases = []
    for case_id, info in ranked:
        row = await session.get(LegalCase, _uuid(case_id)) if _uuid(case_id) else None
        if row is None:
            continue
        from app.rag.casebase import case_dict

        d = case_dict(row)
        cases.append({"id": d["id"], "case_number": d["case_number"], "title": d["title"],
                      "case_type": d["case_type"], "insurance_line": d["insurance_line"], "court": d["court"],
                      "status": d["status_fa"], "outcome": (d["outcome"] or "")[:200],
                      "score": info["score"], "why": info["why"][:4]})
    return {"root": {"type": node_type, "id": node_id}, "cases": cases, "candidates": len(found)}


# --------------------------------------------------------------------------- #
# Fusion
# --------------------------------------------------------------------------- #
async def _vector_case_ids(session: AsyncSession, question: str, *, limit: int = 10) -> list[str]:
    """Document hits → the cases their entries belong to, best first."""
    from app.rag.retriever import retrieve_scored

    if not (question or "").strip():
        return []
    try:
        scored = await retrieve_scored(session, question, top_k=limit)
    except Exception:  # noqa: BLE001 — no embeddings yet, or an empty index
        return []
    doc_ids = []
    for chunk, _distance in scored:
        did = str(chunk.document_id)
        if did not in doc_ids:
            doc_ids.append(did)
    if not doc_ids:
        return []
    return await _cases_of_documents(session, doc_ids)


async def _cases_of_documents(session: AsyncSession, doc_ids: list[str]) -> list[str]:
    ids = [d for d in (_uuid(x) for x in doc_ids) if d]
    if not ids:
        return []
    rows = (await session.execute(
        select(Entry.document_id, Entry.case_id).where(Entry.document_id.in_(ids), Entry.case_id.isnot(None))
    )).all()
    by_doc = {str(doc): str(case) for doc, case in rows}
    out = []
    for did in doc_ids:
        cid = by_doc.get(did)
        if cid and cid not in out:
            out.append(cid)
    return out


def _rrf(ids: list[str]) -> dict[str, float]:
    if not ids:
        return {}
    scores = {cid: 1.0 / (_RRF_K + rank) for rank, cid in enumerate(ids, 1)}
    top = max(scores.values())
    return {cid: s / top for cid, s in scores.items()}


async def similar_cases(
    session: AsyncSession, *, question: str = "", refs: list[dict] | None = None,
    seed_cases: list[dict] | None = None, seed_document_ids: list[str] | None = None,
    anchor_case_number: str | None = None, anchor_case_id: str | None = None,
    top_k: int = 5,
) -> list[dict]:
    """Resembling cases for a question, the articles an answer cited, a set
    of seed cases, and/or an anchor case — each with `score`, `why`, `path`."""
    from app.rag.casebase import get_case, search_cases

    exclude: set[str] = set()
    seeds: list[str] = []
    if anchor_case_id or anchor_case_number:
        anchor = await get_case(session, anchor_case_id or anchor_case_number)
        if anchor:
            seeds.append(anchor["id"])
            exclude.add(anchor["id"])
    for c in seed_cases or []:
        if c.get("id"):
            seeds.append(str(c["id"]))
            exclude.add(str(c["id"]))
    if seed_document_ids:
        for cid in await _cases_of_documents(session, seed_document_ids):
            if cid not in seeds:
                seeds.append(cid)
    law_nodes = [("law", str(r["id"])) for r in (refs or []) if r.get("id")]

    fts_ids = [c["id"] for c in await search_cases(session, question, limit=10)] if question else []
    vec_ids = await _vector_case_ids(session, question)
    # A bare question with nothing cited still gets a graph leg: its best
    # textual hits seed the walk, so what *they* share surfaces too.
    if not seeds and not law_nodes:
        seeds = fts_ids[:3]
    found = await expand(session, case_ids=seeds, nodes=law_nodes)

    fts = _rrf([c for c in fts_ids if c not in exclude])
    vec = _rrf([c for c in vec_ids if c not in exclude])
    top_graph = max((v["score"] for v in found.values()), default=0.0) or 1.0
    scores: dict[str, float] = {}
    for cid in set(fts) | set(vec) | set(found):
        if cid in exclude:
            continue
        scores[cid] = (0.4 * fts.get(cid, 0.0) + 0.3 * vec.get(cid, 0.0)
                       + 0.3 * (found.get(cid, {}).get("score", 0.0) / top_graph))

    # Seed attributes: the same dispute type / insurance line is a reason too.
    seed_attrs: list[tuple[str, str]] = []
    for sid in seeds[:3]:
        row = await session.get(LegalCase, _uuid(sid)) if _uuid(sid) else None
        if row is not None:
            seed_attrs.append((row.case_type or "", row.insurance_line or ""))

    ranked = sorted(scores.items(), key=lambda kv: -kv[1])[:top_k * 2]
    items: list[dict] = []
    for cid, score in ranked:
        case = await get_case(session, cid)
        if not case:
            continue
        why: list[str] = list(found.get(cid, {}).get("why", []))[:4]
        paths = list(found.get(cid, {}).get("paths", []))[:4]
        for ctype, line in seed_attrs:
            if ctype and case.get("case_type") == ctype and not any("هم‌نوع" in w for w in why):
                why.append(f"هم‌نوع: {ctype}")
                score += 0.1
            if line and case.get("insurance_line") == line and not any("رشتهٔ" in w for w in why):
                why.append(f"همان رشتهٔ بیمه: {line}")
                score += 0.05
        if cid in fts:
            why.append("واژه‌های مشترک با پرسش")
        if cid in vec:
            why.append("شباهت معنایی متن")
        items.append({**case, "score": round(min(score, 1.5), 3), "why": why, "path": paths,
                      "graph_score": found.get(cid, {}).get("score", 0.0)})
    items.sort(key=lambda c: -c["score"])
    return items[:top_k]


# --------------------------------------------------------------------------- #
# What worked, what did not
# --------------------------------------------------------------------------- #
_WORKED = re.compile(r"حکم به (?:پرداخت|محکومیت|الزام)|محکومیت|الزام|پذیرفته|محکوم (?:شد|گردید)|رأی به نفع|رای به نفع")
_FAILED = re.compile(r"رد دعوا|قرار رد|منع تعقیب|ابطال|بطلان|بی‌حقی|بیحقی|حکم به رد|برائت")
_PENDING = re.compile(r"در جریان|ارجاع به کارشناس|کارشناسی|تجدیدنظر|اعادهٔ دادرسی|اعاده دادرسی")
_POINTS = ("مرور زمان", "کتمان", "عدم اعلام", "قاعدهٔ نسبی", "قاعده نسبی", "تشدید خطر", "عدم پرداخت حق بیمه",
           "جانشینی", "قائم‌مقامی", "تقصیر", "فاقد گواهینامه", "مستی", "تأخیر", "کارشناسی", "خسارت تأخیر",
           "قصور", "تقلب", "جعل", "عمد", "استثنائات بیمه‌نامه", "فرانشیز", "بازیافت")


def _point(case: dict) -> str:
    haystack = " ".join(str(case.get(k) or "") for k in ("outcome", "summary", "title"))
    hits = [p for p in _POINTS if p in haystack]
    return "، ".join(dict.fromkeys(hits[:3]))


def outcome_lessons(cases: list[dict]) -> dict:
    """Rule-based reading of the outcomes: which claims succeeded, which were
    rejected, which are still open — and the point each one turned on."""
    worked, failed, pending, unknown = [], [], [], []
    for case in cases:
        outcome = str(case.get("outcome") or "")
        status = case.get("status") or ""
        item = {"case_number": case.get("case_number"), "title": case.get("title"),
                "outcome": outcome[:160], "point": _point(case)}
        if _FAILED.search(outcome):
            failed.append(item)
        elif _WORKED.search(outcome):
            worked.append(item)
        elif _PENDING.search(outcome) or status in ("open", "appeal"):
            pending.append(item)
        else:
            unknown.append(item)
    return {"worked": worked, "failed": failed, "pending": pending, "unknown": unknown,
            "summary": f"{len(worked)} پذیرفته‌شده · {len(failed)} ردشده · {len(pending)} در جریان"
                       + (f" · {len(unknown)} نامشخص" if unknown else "")}


# --------------------------------------------------------------------------- #
# The advice stage
# --------------------------------------------------------------------------- #
_ADVICE_SYSTEM = (
    "You are a Persian insurance-law assistant writing the comparative part of an "
    "answer. You get the question, the answer already given, and numbered past "
    "cases from the same archive with their outcomes and why each resembles the "
    "question. Write a short «تحلیل تطبیقی»: which past cases are closest and why, "
    "what worked and what failed in them, and what that suggests for this "
    "question — every claim cited with the case number in brackets like [7], "
    "exactly as numbered. Do not repeat the statute answer. If the cases do not "
    "bear on the question, say so in one line. Reply in Persian, at most 180 words."
)


def case_blocks(cases: list[dict], *, offset: int) -> tuple[str, list[dict]]:
    """Numbered evidence blocks for the similar cases, continuing an existing
    `[n]` sequence, plus the matching provenance items."""
    from app.rag import provenance as prov

    blocks, evidence = [], []
    for i, c in enumerate(cases, offset + 1):
        why = "؛ ".join(c.get("why") or [])
        blocks.append(
            f"[{i}] پروندهٔ {c.get('case_number')} — {c.get('title') or ''}\n"
            f"نوع: {c.get('case_type') or '—'} | رشته: {c.get('insurance_line') or '—'} | "
            f"مرجع: {c.get('court') or '—'} | وضعیت: {c.get('status_fa') or ''}\n"
            f"نتیجه: {c.get('outcome') or '—'}" + (f"\nعلت شباهت: {why}" if why else "")
        )
        evidence.extend(prov.evidence_from_cases([c], offset=i - 1))
    return "\n\n".join(blocks), evidence


async def advise(
    llm: LLMProvider, *, question: str, answer: str, cases: list[dict], lessons: dict,
    offset: int, max_tokens: int = 900,
):
    blocks, _ = case_blocks(cases, offset=offset)
    prompt = (
        f"Question: {question}\n\nAnswer so far:\n{(answer or '')[:1500]}\n\n"
        f"Outcome tally: {lessons.get('summary', '')}\n\nPast cases:\n{blocks}\n\n"
        "Write the comparative analysis in Persian, citing [n]."
    )
    return await llm.generate(prompt, system=_ADVICE_SYSTEM, max_tokens=max_tokens, reasoning_effort="low")


def enabled() -> bool:
    return os.environ.get("SIMILAR_STAGE", "1") != "0"


async def stage(
    session: AsyncSession, llm: LLMProvider, *, question: str, answer: str,
    refs: list[dict] | None = None, seed_cases: list[dict] | None = None,
    seed_document_ids: list[str] | None = None, offset: int = 0, top_k: int = 5,
) -> dict:
    """The second pass after an answer: similar cases, lessons, advice.

    Returns `{}` when disabled or nothing resembles the question; otherwise
    `{similar_cases, lessons, advice, advice_model, advice_usage, similar_evidence, steps}`.
    """
    if not enabled():
        return {}
    t0 = time.perf_counter()
    cases = await similar_cases(session, question=question, refs=refs, seed_cases=seed_cases,
                                seed_document_ids=seed_document_ids, top_k=top_k)
    find_ms = round((time.perf_counter() - t0) * 1000)
    if not cases:
        return {"similar_cases": [], "steps": [{"name": "پرونده‌های مشابه از گراف", "detail": "موردی یافت نشد", "ms": find_ms}]}
    lessons = outcome_lessons(cases)
    paths = sum(len(c.get("path") or []) for c in cases)
    _blocks, evidence = case_blocks(cases, offset=offset)
    out = {
        "similar_cases": cases, "lessons": lessons, "similar_evidence": evidence,
        "steps": [{"name": "پرونده‌های مشابه از گراف",
                   "detail": f"{len(cases)} پرونده · {paths} مسیر در گراف · {lessons['summary']}", "ms": find_ms}],
    }
    if os.environ.get("SIMILAR_STAGE_LLM", "1") != "0":
        t1 = time.perf_counter()
        try:
            resp = await advise(llm, question=question, answer=answer, cases=cases, lessons=lessons, offset=offset)
            from app.llm.meter import usage_of

            out.update({"advice": resp.text, "advice_model": resp.model, "advice_usage": usage_of([resp])})
            out["steps"].append({"name": "تحلیل تطبیقی", "detail": f"مدل {resp.model} روی {len(cases)} پروندهٔ مشابه",
                                 "ms": round((time.perf_counter() - t1) * 1000)})
        except Exception as error:  # noqa: BLE001 — the list is the deliverable; advice is extra
            out["steps"].append({"name": "تحلیل تطبیقی", "detail": f"ناموفق: {type(error).__name__}: {error}"[:200],
                                 "ms": round((time.perf_counter() - t1) * 1000)})
    return out


async def graph_nodes_of(session: AsyncSession, node_type: str, node_id: str, *, depth: int = 1) -> dict:
    return await graph.neighborhood(session, node_type, node_id, depth=depth)

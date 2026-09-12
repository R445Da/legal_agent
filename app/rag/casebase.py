"""
The case archive as first-class records: `legal_cases`, `persons`,
`organizations`, the typed junctions, and the graph edges that mirror them.

`sync_entry()` is the one write path. It runs after an Entry is committed
(pipeline or seed) and after an Entry is edited, and it makes the relational
side agree with the Entry's JSON: the case row exists, the parties are Person /
Organization rows, the cited articles are `case_references`, and `graph_edges`
carries all of it. Everything else here is reads for the UI, the API and the
model's tools.
"""

from __future__ import annotations

import re
import uuid
from collections import Counter

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    TS_CONFIG, CaseParty, CaseReference, Entry, LegalCase, LegalReference, Organization, Person,
)
from app.llm.base import LLMProvider
from app.rag import graph, lawbase
from app.rag.textnorm import normalize_fa

ROLE_FA = {
    "khahan": "خواهان", "khande": "خوانده", "vakil_khahan": "وکیل خواهان",
    "vakil_khande": "وکیل خوانده", "ghazi": "قاضی", "mottaham": "متهم", "shaki": "شاکی",
    "karshenas": "کارشناس", "bimegar": "بیمه‌گر", "bimegozar": "بیمه‌گذار",
    "zianide": "زیان‌دیده", "vakil": "وکیل", "court": "مرجع", "mentioned": "ذکرشده", "other": "سایر",
}
STATUS_FA = {"open": "جاری", "closed": "مختومه", "appeal": "تجدیدنظر", "archived": "بایگانی"}

_ORG_HINTS = (
    "شرکت", "بیمه", "بانک", "سازمان", "صندوق", "اداره", "مؤسسه", "موسسه", "دادگاه", "شعبه",
    "کارخانه", "شهرداری", "اتحادیه", "دانشگاه", "بیمارستان", "هلدینگ", "تعاونی", "وزارت",
    "پتروشیمی", "کارگزاری", "نمایندگی", "دیوان", "شورا", "هیئت", "هیأت", "درمانگاه", "کلینیک",
)
_HONORIFICS = ("جناب آقای ", "سرکار خانم ", "آقای ", "خانم ", "جناب ", "دکتر ", "مهندس ", "استاد ")


def norm_name(name: str) -> str:
    n = " ".join(normalize_fa(str(name or "")).split())
    for h in _HONORIFICS:
        if n.startswith(h):
            n = n[len(h):]
            break
    return n.strip(" .،")


def is_org(name: str) -> bool:
    n = name or ""
    return any(h in n for h in _ORG_HINTS)


def org_kind(name: str) -> str:
    n = name or ""
    if "بیمه مرکزی" in n:
        return "regulator"
    if "بیمه" in n and ("شرکت" in n or "سهامی" in n or n.startswith("بیمه")):
        return "insurer"
    if "دادگاه" in n or "شعبه" in n or "دیوان" in n or "شورا" in n:
        return "court"
    if "صندوق" in n:
        return "fund"
    if "بانک" in n:
        return "bank"
    if any(k in n for k in ("سازمان", "اداره", "وزارت", "شهرداری")):
        return "agency"
    return "company"


# --------------------------------------------------------------------------- #
# Upserts
# --------------------------------------------------------------------------- #
async def get_or_create_person(session: AsyncSession, name: str, *, role: str | None = None) -> Person:
    key = norm_name(name)
    row = await session.scalar(select(Person).where(Person.norm_name == key))
    if row is None:
        row = Person(name=key, norm_name=key, roles=[])
        session.add(row)
        await session.flush()
    if role and role not in (row.roles or []):
        row.roles = list(row.roles or []) + [role]
    return row


async def get_or_create_org(session: AsyncSession, name: str, *, role: str | None = None) -> Organization:
    key = norm_name(name)
    row = await session.scalar(select(Organization).where(Organization.norm_name == key))
    if row is None:
        row = Organization(name=key, norm_name=key, kind=org_kind(key), roles=[])
        session.add(row)
        await session.flush()
    if role and role not in (row.roles or []):
        row.roles = list(row.roles or []) + [role]
    return row


async def get_or_create_case(session: AsyncSession, case_number: str) -> LegalCase:
    number = normalize_fa(case_number).strip()
    row = await session.scalar(select(LegalCase).where(LegalCase.case_number == number))
    if row is None:
        row = LegalCase(case_number=number, status="open")
        session.add(row)
        await session.flush()
    return row


def _first(*values):
    for v in values:
        if v:
            return v
    return None


def _amount(value) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    digits = re.sub(r"[^0-9]", "", normalize_fa(str(value)))
    return int(digits) if digits else None


async def sync_entry(session: AsyncSession, entry: Entry, *, case_fields: dict | None = None) -> LegalCase | None:
    """Make the relational + graph side agree with one Entry. Idempotent.

    Returns the case the entry now belongs to, or None when the entry carries
    no case number (it then stays an incomplete, unattached record — the
    review queue's job)."""
    ent = entry.entities if isinstance(entry.entities, dict) else {}
    number = str(ent.get("case_number") or "").strip()
    fields = case_fields or {}

    # Entry-level edges are rebuilt every time.
    await graph.unlink_node(session, "entry", entry.id)
    if entry.document_id:
        await graph.link(session, "entry", entry.id, "HAS_DOCUMENT", "document", entry.document_id)

    if not number:
        entry.case_id = None
        return None

    case = await get_or_create_case(session, number)
    case.title = _first(fields.get("title"), case.title, entry.title)
    case.court = _first(fields.get("court"), ent.get("court"), case.court)
    case.case_type = _first(fields.get("case_type"), ent.get("case_type"), case.case_type)
    case.insurance_line = _first(fields.get("insurance_line"), ent.get("insurance_line"), case.insurance_line)
    case.branch = _first(fields.get("branch"), ent.get("branch"), case.branch)
    case.group = _first(fields.get("group"), ent.get("group"), case.group)
    case.stage = _first(fields.get("stage"), ent.get("stage"), case.stage)
    case.status = _first(fields.get("status"), ent.get("status"), case.status) or "open"
    case.filed_date = _first(fields.get("filed_date"), ent.get("filed_date"), case.filed_date)
    case.decided_date = _first(fields.get("decided_date"), ent.get("decided_date"), case.decided_date)
    case.outcome = _first(fields.get("outcome"), ent.get("outcome"), case.outcome)
    case.summary = _first(fields.get("summary"), case.summary, entry.summary)
    amount = _amount(_first(fields.get("claim_amount"), ent.get("claim_amount")))
    if amount is not None:
        case.claim_amount = amount
    case.meta = {**(case.meta or {}), **(fields.get("meta") or {})}
    entry.case_id = case.id

    # Rebuild this case's typed relations + edges from *all* of its entries, so
    # an edit to one entry never leaves a stale party or citation behind.
    await session.execute(delete(CaseParty).where(CaseParty.case_id == case.id))
    await session.execute(delete(CaseReference).where(CaseReference.case_id == case.id))
    await graph.unlink_node(session, "case", case.id)
    await session.flush()

    siblings = (await session.execute(
        select(Entry).where(Entry.case_id == case.id)
    )).scalars().all()
    if entry not in siblings:
        siblings = list(siblings) + [entry]

    seen_party: set[tuple[str, str, str]] = set()
    seen_ref: set[str] = set()
    for e in siblings:
        await graph.link(session, "case", case.id, "HAS_ENTRY", "entry", e.id)
        e_ent = e.entities if isinstance(e.entities, dict) else {}

        for party in e.parties or []:
            if not isinstance(party, dict) or not party.get("name"):
                continue
            name, role = str(party["name"]), str(party.get("role") or "other")
            if is_org(name):
                org = await get_or_create_org(session, name, role=role)
                key = ("org", str(org.id), role)
                if key in seen_party:
                    continue
                seen_party.add(key)
                session.add(CaseParty(case_id=case.id, org_id=org.id, role=role))
                await graph.link(session, "case", case.id, "PARTY", "org", org.id,
                                 meta={"role": role, "role_fa": ROLE_FA.get(role, role)})
            else:
                person = await get_or_create_person(session, name, role=role)
                key = ("person", str(person.id), role)
                if key in seen_party:
                    continue
                seen_party.add(key)
                session.add(CaseParty(case_id=case.id, person_id=person.id, role=role))
                await graph.link(session, "case", case.id, "PARTY", "person", person.id,
                                 meta={"role": role, "role_fa": ROLE_FA.get(role, role)})

        for rep in e.representation or []:
            if not isinstance(rep, dict) or not rep.get("lawyer") or not rep.get("client"):
                continue
            lawyer = await get_or_create_person(session, str(rep["lawyer"]), role="vakil")
            client_name = str(rep["client"])
            if is_org(client_name):
                client = await get_or_create_org(session, client_name)
                await graph.link(session, "person", lawyer.id, "REPRESENTS", "org", client.id,
                                 meta={"case": case.case_number})
            else:
                client = await get_or_create_person(session, client_name)
                await graph.link(session, "person", lawyer.id, "REPRESENTS", "person", client.id,
                                 meta={"case": case.case_number})

        for org_name in (e_ent.get("orgs") or []):
            if str(org_name).strip() and is_org(str(org_name)):
                org = await get_or_create_org(session, str(org_name))
                key = ("org", str(org.id), "mentioned")
                if key not in seen_party:
                    seen_party.add(key)
                    await graph.link(session, "case", case.id, "PARTY", "org", org.id,
                                     meta={"role": "mentioned", "role_fa": "ذکرشده"})

        court = re.split(r"\s+[—–-]\s+", str(e_ent.get("court") or "").strip())[0]
        if court:
            court_org = await get_or_create_org(session, court, role="court")
            court_org.kind = "court"
            await graph.link(session, "case", case.id, "HEARD_AT", "org", court_org.id)

        for ref in e.legal_refs or []:
            if not isinstance(ref, dict) or not ref.get("ref_id"):
                continue
            if ref["ref_id"] in seen_ref:
                continue
            seen_ref.add(ref["ref_id"])
            try:
                rid = uuid.UUID(str(ref["ref_id"]))
            except ValueError:
                continue
            session.add(CaseReference(case_id=case.id, ref_id=rid, context=ref.get("context"),
                                      used_by=ref.get("used_by"), weight=1.0))
            await graph.link(session, "case", case.id, "CITES", "law", rid,
                             meta={"context": (ref.get("context") or "")[:120]})

        for tag in e.tags or []:
            if str(tag).strip():
                await graph.link(session, "case", case.id, "LABELED", "label", str(tag).strip())

        for link in e.related or []:
            if isinstance(link, dict) and link.get("entry_id"):
                other = await session.scalar(select(Entry.case_id).where(Entry.id == uuid.UUID(str(link["entry_id"]))))
                if other and other != case.id:
                    await graph.link(session, "case", case.id, "SIMILAR_TO", "case", other,
                                     weight=float(link.get("score") or 0.5))

    await session.flush()
    return case


async def prune_orphans(session: AsyncSession) -> dict:
    """Drop persons / organizations that no case references and no edge touches
    (left behind when their only entry was deleted)."""
    from app.db.models import GraphEdge

    removed = {"persons": 0, "orgs": 0}
    for model, col, key in ((Person, CaseParty.person_id, "persons"), (Organization, CaseParty.org_id, "orgs")):
        ntype = "person" if key == "persons" else "org"
        rows = (await session.execute(select(model))).scalars().all()
        for row in rows:
            in_party = await session.scalar(select(func.count()).select_from(CaseParty).where(col == row.id))
            if in_party:
                continue
            nid = str(row.id)
            in_graph = await session.scalar(select(func.count()).select_from(GraphEdge).where(
                ((GraphEdge.src_type == ntype) & (GraphEdge.src_id == nid))
                | ((GraphEdge.dst_type == ntype) & (GraphEdge.dst_id == nid))
            ))
            if in_graph:
                continue
            await session.delete(row)
            removed[key] += 1
    await session.flush()
    return removed


async def resync_all(session: AsyncSession) -> int:
    """Rebuild cases/persons/orgs/edges from every Entry (after a bulk load)."""
    entries = (await session.execute(select(Entry).order_by(Entry.created_at))).scalars().all()
    n = 0
    for e in entries:
        await sync_entry(session, e)
        n += 1
    await session.flush()
    return n


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #
def case_dict(c: LegalCase) -> dict:
    return {
        "id": str(c.id), "case_number": c.case_number, "title": c.title,
        "case_type": c.case_type, "insurance_line": c.insurance_line, "court": c.court,
        "branch": c.branch, "group": c.group, "status": c.status,
        "status_fa": STATUS_FA.get(c.status, c.status), "stage": c.stage,
        "filed_date": c.filed_date, "decided_date": c.decided_date, "outcome": c.outcome,
        "claim_amount": c.claim_amount, "summary": c.summary, "meta": c.meta or {},
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


async def list_cases(
    session: AsyncSession, *, case_type: str | None = None, insurance_line: str | None = None,
    status: str | None = None, court: str | None = None, q: str | None = None, limit: int = 500,
) -> list[dict]:
    stmt = select(LegalCase).order_by(LegalCase.filed_date.desc().nullslast(), LegalCase.created_at.desc())
    if case_type:
        stmt = stmt.where(LegalCase.case_type == case_type)
    if insurance_line:
        stmt = stmt.where(LegalCase.insurance_line == insurance_line)
    if status:
        stmt = stmt.where(LegalCase.status == status)
    if court:
        stmt = stmt.where(LegalCase.court == court)
    if q:
        needle = f"%{normalize_fa(q).strip()}%"
        stmt = stmt.where(
            LegalCase.case_number.ilike(needle) | LegalCase.title.ilike(needle) | LegalCase.summary.ilike(needle)
        )
    rows = (await session.execute(stmt.limit(limit))).scalars().all()
    return [case_dict(r) for r in rows]


async def get_case(session: AsyncSession, case_id_or_number: str) -> dict | None:
    """Case + parties + references + entries, resolved to names."""
    row = None
    try:
        row = await session.get(LegalCase, uuid.UUID(str(case_id_or_number)))
    except ValueError:
        pass
    if row is None:
        row = await session.scalar(
            select(LegalCase).where(LegalCase.case_number == normalize_fa(str(case_id_or_number)).strip())
        )
    if row is None:
        return None
    out = case_dict(row)

    parties = (await session.execute(
        select(CaseParty, Person.name, Organization.name)
        .outerjoin(Person, Person.id == CaseParty.person_id)
        .outerjoin(Organization, Organization.id == CaseParty.org_id)
        .where(CaseParty.case_id == row.id)
    )).all()
    out["parties"] = [
        {"id": str(cp.person_id or cp.org_id), "type": "person" if cp.person_id else "org",
         "name": pname or oname, "role": cp.role, "role_fa": ROLE_FA.get(cp.role, cp.role)}
        for cp, pname, oname in parties
    ]
    refs = (await session.execute(
        select(CaseReference, LegalReference)
        .join(LegalReference, LegalReference.id == CaseReference.ref_id)
        .where(CaseReference.case_id == row.id)
    )).all()
    out["references"] = [
        {**lawbase.as_dict(ref), "context": cr.context, "used_by": cr.used_by, "weight": cr.weight}
        for cr, ref in refs
    ]
    entries = (await session.execute(
        select(Entry).where(Entry.case_id == row.id).order_by(Entry.created_at)
    )).scalars().all()
    out["entries"] = [
        {"id": str(e.id), "title": e.title, "kind": e.kind, "summary": e.summary,
         "document_id": str(e.document_id) if e.document_id else None,
         "events": e.events or [], "tags": e.tags or [],
         "created_at": e.created_at.isoformat() if e.created_at else None}
        for e in entries
    ]
    events = []
    for e in entries:
        for ev in e.events or []:
            if isinstance(ev, dict):
                events.append({**ev, "entry_id": str(e.id)})
    events.sort(key=lambda ev: str(ev.get("date") or ""))
    out["events"] = events
    return out


async def update_case(session: AsyncSession, case_id: str, patch: dict) -> dict | None:
    row = await session.get(LegalCase, uuid.UUID(str(case_id)))
    if row is None:
        return None
    allowed = ("title", "case_type", "insurance_line", "court", "branch", "group", "status",
               "stage", "filed_date", "decided_date", "outcome", "summary")
    for key in allowed:
        if key in patch:
            setattr(row, key, patch[key] or None)
    if "claim_amount" in patch:
        row.claim_amount = _amount(patch["claim_amount"])
    if isinstance(patch.get("meta"), dict):
        row.meta = {**(row.meta or {}), **patch["meta"]}
    await session.flush()
    return case_dict(row)


async def search_cases(session: AsyncSession, text: str, *, limit: int = 8) -> list[dict]:
    """FTS over the case table (number, title, type, line, court, summary, outcome)."""
    tokens = [t.strip("؟?.,،:؛«»\"'()[]") for t in normalize_fa(text or "").split()]
    tokens = [t for t in tokens if len(t) >= 3]
    if not tokens:
        return []
    total = await session.scalar(select(func.count()).select_from(LegalCase)) or 0
    if not total:
        return []
    freq: dict[str, int] = {}
    for tok in set(tokens):
        freq[tok] = await session.scalar(
            select(func.count()).select_from(LegalCase).where(
                LegalCase.text_search.op("@@")(func.to_tsquery(TS_CONFIG, tok))
            )
        ) or 0
    useful = [t for t, n in freq.items() if 0 < n <= total * 0.5]
    if not useful:
        present = sorted((n, t) for t, n in freq.items() if n)
        if not present:
            return []
        useful = [present[0][1]]
    tsq = func.to_tsquery(TS_CONFIG, " | ".join(useful))
    rank = func.ts_rank_cd(LegalCase.text_search, tsq)
    rows = (await session.execute(
        select(LegalCase).where(LegalCase.text_search.op("@@")(tsq)).order_by(rank.desc()).limit(limit)
    )).scalars().all()
    return [case_dict(r) for r in rows]


async def entity_profile(session: AsyncSession, kind: str, key: str) -> dict | None:
    """Everything about one person or organization: roles, every case with the
    role held there, and the counterparties. `key` is an id or a name."""
    model = Person if kind == "person" else Organization
    row = None
    try:
        row = await session.get(model, uuid.UUID(str(key)))
    except ValueError:
        pass
    if row is None:
        row = await session.scalar(select(model).where(model.norm_name == norm_name(key)))
    if row is None:
        # loose name match, for names typed by hand
        row = await session.scalar(select(model).where(model.norm_name.ilike(f"%{norm_name(key)}%")))
    if row is None:
        return None

    col = CaseParty.person_id if kind == "person" else CaseParty.org_id
    rows = (await session.execute(
        select(CaseParty.role, LegalCase).join(LegalCase, LegalCase.id == CaseParty.case_id)
        .where(col == row.id).order_by(LegalCase.filed_date.desc().nullslast())
    )).all()
    cases = []
    seen = set()
    for role, case in rows:
        if str(case.id) in seen:
            continue
        seen.add(str(case.id))
        cases.append({**case_dict(case), "role": role, "role_fa": ROLE_FA.get(role, role)})

    # Representation edges (lawyer <-> client) live only in the graph.
    edges = await graph.edges_of(session, kind, row.id)
    represents, represented_by = [], []
    for e in edges:
        if e.relation != "REPRESENTS":
            continue
        if e.src_type == kind and e.src_id == str(row.id):
            represents.append({"type": e.dst_type, "id": e.dst_id, "case": (e.meta or {}).get("case")})
        else:
            represented_by.append({"type": e.src_type, "id": e.src_id, "case": (e.meta or {}).get("case")})
    for lst in (represents, represented_by):
        for item in lst:
            m = Person if item["type"] == "person" else Organization
            obj = await session.get(m, uuid.UUID(item["id"]))
            item["name"] = obj.name if obj else item["id"]

    outcomes = Counter((c.get("outcome") or "—")[:40] for c in cases)
    lines = Counter(c.get("insurance_line") or "—" for c in cases)
    types = Counter(c.get("case_type") or "—" for c in cases)
    return {
        "id": str(row.id), "type": kind, "name": row.name, "roles": row.roles or [],
        "roles_fa": [ROLE_FA.get(r, r) for r in (row.roles or [])],
        "kind": getattr(row, "kind", None), "meta": row.meta or {},
        "cases": cases, "case_count": len(cases),
        "represents": represents, "represented_by": represented_by,
        "by_line": lines.most_common(), "by_type": types.most_common(),
        "by_outcome": outcomes.most_common(6),
    }


async def list_entities(session: AsyncSession, kind: str, *, q: str | None = None, limit: int = 300) -> list[dict]:
    model = Person if kind == "person" else Organization
    col = CaseParty.person_id if kind == "person" else CaseParty.org_id
    stmt = (
        select(model, func.count(func.distinct(CaseParty.case_id)).label("n"))
        .outerjoin(CaseParty, col == model.id)
        .group_by(model.id).order_by(func.count(func.distinct(CaseParty.case_id)).desc(), model.name)
        .limit(limit)
    )
    if q:
        stmt = stmt.where(model.norm_name.ilike(f"%{norm_name(q)}%"))
    rows = (await session.execute(stmt)).all()
    return [
        {"id": str(r.id), "name": r.name, "roles": r.roles or [],
         "roles_fa": [ROLE_FA.get(x, x) for x in (r.roles or [])],
         "kind": getattr(r, "kind", None), "cases": n}
        for r, n in rows
    ]


async def archive_stats(session: AsyncSession) -> dict:
    """Aggregates over the case table — the numbers the statistics view shows."""
    async def _group(col):
        rows = (await session.execute(
            select(col, func.count()).where(col.isnot(None)).group_by(col).order_by(func.count().desc())
        )).all()
        return [{"name": r[0], "count": r[1]} for r in rows]

    total = await session.scalar(select(func.count()).select_from(LegalCase)) or 0
    amounts = (await session.execute(
        select(func.sum(LegalCase.claim_amount), func.avg(LegalCase.claim_amount))
        .where(LegalCase.claim_amount.isnot(None))
    )).one()
    laws = (await session.execute(
        select(LegalReference.law_title, LegalReference.article_no, func.count())
        .join(CaseReference, CaseReference.ref_id == LegalReference.id)
        .group_by(LegalReference.law_title, LegalReference.article_no)
        .order_by(func.count().desc()).limit(15)
    )).all()
    by_month: dict[str, int] = {}
    for (d,) in (await session.execute(select(LegalCase.filed_date).where(LegalCase.filed_date.isnot(None)))).all():
        key = normalize_fa(str(d))[:7]
        by_month[key] = by_month.get(key, 0) + 1
    return {
        "cases": total,
        "persons": await session.scalar(select(func.count()).select_from(Person)) or 0,
        "orgs": await session.scalar(select(func.count()).select_from(Organization)) or 0,
        "laws": await session.scalar(select(func.count()).select_from(LegalReference)) or 0,
        "citations": await session.scalar(select(func.count()).select_from(CaseReference)) or 0,
        "claim_total": int(amounts[0] or 0), "claim_avg": int(amounts[1] or 0),
        "by_type": await _group(LegalCase.case_type),
        "by_line": await _group(LegalCase.insurance_line),
        "by_status": [{**r, "name_fa": STATUS_FA.get(r["name"], r["name"])} for r in await _group(LegalCase.status)],
        "by_court": (await _group(LegalCase.court))[:12],
        "by_group": await _group(LegalCase.group),
        "top_laws": [{"law": l, "article": a, "count": n} for l, a, n in laws],
        "by_month": sorted(by_month.items()),
    }


_CASE_SYSTEM = (
    "You are the assistant of a Persian insurance-law case archive. Answer the "
    "question from the case records provided, citing each record as [n]. Say "
    "which cases support the answer, the outcome where known, and the articles "
    "they relied on. If the records do not answer it, say so. Reply in Persian."
)


async def answer_case_question(
    session: AsyncSession, llm: LLMProvider, question: str, *, top_k: int = 6, max_tokens: int = 1400,
) -> dict:
    """The «case archive» route: FTS over cases (+ their cited articles), then
    an answer with [n] citations to case records."""
    import time

    t0 = time.perf_counter()
    hits = await search_cases(session, question, limit=top_k)
    full = [await get_case(session, h["id"]) for h in hits]
    retrieve_ms = round((time.perf_counter() - t0) * 1000)
    if not full:
        return {"answer": "پرونده‌ای مرتبط با این پرسش در بایگانی یافت نشد.", "cases": [],
                "steps": [{"name": "جستجوی بایگانی پرونده‌ها", "detail": "بدون نتیجه", "ms": retrieve_ms}]}
    blocks = []
    for i, c in enumerate(full, 1):
        parties = "، ".join(f"{p['name']} ({p['role_fa']})" for p in c["parties"][:6])
        refs = "؛ ".join(r["cite"] + (f" — {r['context']}" if r.get("context") else "") for r in c["references"][:6])
        blocks.append(
            f"[{i}] پروندهٔ {c['case_number']} — {c['title'] or ''}\n"
            f"نوع: {c['case_type'] or '—'} | رشته: {c['insurance_line'] or '—'} | مرجع: {c['court'] or '—'} | "
            f"وضعیت: {c['status_fa']} | تاریخ: {c['filed_date'] or '—'}\n"
            f"طرفین: {parties or '—'}\nمستندات: {refs or '—'}\n"
            f"خلاصه: {c['summary'] or '—'}\nنتیجه: {c['outcome'] or '—'}"
        )
    t1 = time.perf_counter()
    resp = await llm.generate(
        "Case records:\n\n" + "\n\n".join(blocks) + f"\n\nQuestion: {question}\n\nAnswer in Persian, citing [n].",
        system=_CASE_SYSTEM, max_tokens=max_tokens, reasoning_effort="low",
    )
    from app.llm.meter import usage_of

    return {
        "answer": resp.text, "cases": full, "model": resp.model, "latency_ms": resp.latency_ms,
        "usage": usage_of([resp]), "reasoning": resp.reasoning,
        "steps": [
            {"name": "جستجوی بایگانی پرونده‌ها", "detail": f"{len(full)} پرونده با طرفین و مستندات", "ms": retrieve_ms},
            {"name": "پاسخ با استناد به پرونده‌ها", "detail": f"مدل {resp.model}",
             "ms": round((time.perf_counter() - t1) * 1000)},
        ],
    }

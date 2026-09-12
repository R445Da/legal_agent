"""
Build an Obsidian canvas of the legal archive: cases, statute references,
people, and organizations, colored by type and grouped into labeled zones,
with case->law citation edges and case->person/org role edges.

    python -m scripts.build_legal_canvas
    python -m scripts.build_legal_canvas --watch          # rebuild whenever the data changes
    python -m scripts.build_legal_canvas --watch --interval 10
    python -m scripts.build_legal_canvas --out path/to/file.canvas
"""

import argparse
import asyncio
import math
import time

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.engine import resolve_database_url
from app.db.models import (
    CaseParty,
    CaseReference,
    LegalCase,
    LegalReference,
    Organization,
    Person,
)

DEFAULT_OUT = "graphify-out/obsidian/legal-archive.canvas"

COLORS = {"case": "1", "law": "5", "person": "4", "org": "6"}
CASE_W, CASE_H = 300, 130
LAW_W, LAW_H = 280, 120
PERSON_W, PERSON_H = 220, 70
ORG_W, ORG_H = 220, 70
LAW_COLS, CASE_COLS, PERSON_COLS, ORG_COLS = 9, 12, 10, 9


def truncate(s, n):
    if not s:
        return ""
    s = str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def grid_layout(items, cols, node_w, node_h, gap_x, gap_y, origin_x, origin_y):
    positions = {}
    for i, item_id in enumerate(items):
        row, col = divmod(i, cols)
        positions[item_id] = (
            origin_x + col * (node_w + gap_x),
            origin_y + row * (node_h + gap_y),
        )
    rows = math.ceil(len(items) / cols) if items else 0
    return positions, cols * (node_w + gap_x), rows * (node_h + gap_y)


def group_node(gid, label, x, y, w, h, color):
    return {
        "id": gid,
        "type": "group",
        "label": label,
        "x": x - 40,
        "y": y - 70,
        "width": w + 40,
        "height": h + 100,
        "color": color,
    }


async def fetch_state(session):
    cases = (await session.scalars(select(LegalCase))).all()
    refs = (await session.scalars(select(LegalReference))).all()
    persons = (await session.scalars(select(Person))).all()
    orgs = (await session.scalars(select(Organization))).all()
    parties = (await session.scalars(select(CaseParty))).all()
    citerefs = (await session.scalars(select(CaseReference))).all()
    return cases, refs, persons, orgs, parties, citerefs


async def fetch_fingerprint(session) -> tuple:
    """Cheap change signal: row counts across every table this canvas draws from."""
    counts = []
    for model in (LegalCase, LegalReference, Person, Organization, CaseParty, CaseReference):
        counts.append(await session.scalar(select(func.count()).select_from(model)))
    return tuple(counts)


def build_canvas(cases, refs, persons, orgs, parties, citerefs) -> dict:
    nodes, edges = [], []

    law_pos, law_w, law_h = grid_layout([r.id for r in refs], LAW_COLS, LAW_W, LAW_H, 30, 30, 0, 0)
    case_pos, case_w, case_h = grid_layout(
        [c.id for c in cases], CASE_COLS, CASE_W, CASE_H, 30, 30, law_w + 200, 0
    )
    person_pos, person_w, person_h = grid_layout(
        [p.id for p in persons], PERSON_COLS, PERSON_W, PERSON_H, 24, 24, 0, max(law_h, case_h) + 200
    )
    org_pos, org_w, org_h = grid_layout(
        [o.id for o in orgs], ORG_COLS, ORG_W, ORG_H, 24, 24, person_w + 150, max(law_h, case_h) + 200
    )

    for r in refs:
        x, y = law_pos[r.id]
        body = (
            f"### {r.law_title or ''} — ماده {r.article_no or '-'}\n"
            f"{truncate(r.title, 60)}\n\n{truncate(r.text, 180)}"
        )
        nodes.append(
            {"id": f"law_{r.id}", "type": "text", "text": body, "x": x, "y": y, "width": LAW_W, "height": LAW_H, "color": COLORS["law"]}
        )

    for c in cases:
        x, y = case_pos[c.id]
        body = (
            f"### {c.case_number}\n{truncate(c.title, 70)}\n\n"
            f"نوع: {c.case_type or '—'} | رشته: {c.insurance_line or '—'}\n"
            f"مرجع: {truncate(c.court, 30)} — شعبه {c.branch or '—'}\n"
            f"وضعیت: {c.status} ({c.stage or '—'})\n"
            f"نتیجه: {truncate(c.outcome, 60) or '—'}"
        )
        nodes.append(
            {"id": f"case_{c.id}", "type": "text", "text": body, "x": x, "y": y, "width": CASE_W, "height": CASE_H, "color": COLORS["case"]}
        )

    for p in persons:
        x, y = person_pos[p.id]
        roles = p.roles or []
        if isinstance(roles, str):
            roles = [roles]
        body = f"**{p.name}**\n{', '.join(roles) if roles else '—'}"
        nodes.append(
            {"id": f"person_{p.id}", "type": "text", "text": body, "x": x, "y": y, "width": PERSON_W, "height": PERSON_H, "color": COLORS["person"]}
        )

    for o in orgs:
        x, y = org_pos[o.id]
        body = f"**{o.name}**\n{o.kind or '—'}"
        nodes.append(
            {"id": f"org_{o.id}", "type": "text", "text": body, "x": x, "y": y, "width": ORG_W, "height": ORG_H, "color": COLORS["org"]}
        )

    nodes.insert(0, group_node("grp_law", "قوانین (Laws)", 0, 0, law_w, law_h, COLORS["law"]))
    nodes.insert(1, group_node("grp_case", "پرونده‌ها (Cases)", law_w + 200, 0, case_w, case_h, COLORS["case"]))
    nodes.insert(2, group_node("grp_person", "اشخاص (People)", 0, max(law_h, case_h) + 200, person_w, person_h, COLORS["person"]))
    nodes.insert(
        3,
        group_node(
            "grp_org", "سازمان‌ها (Organizations)", person_w + 150, max(law_h, case_h) + 200, org_w, org_h, COLORS["org"]
        ),
    )

    eid = 0
    for cr in citerefs:
        eid += 1
        label = truncate((cr.used_by or "") + (" — " + cr.context if cr.context else ""), 50).strip(" —")
        edges.append(
            {
                "id": f"e{eid}",
                "fromNode": f"case_{cr.case_id}",
                "fromSide": "left",
                "toNode": f"law_{cr.ref_id}",
                "toSide": "right",
                "color": COLORS["law"],
                "label": label or "استناد",
            }
        )

    for pr in parties:
        eid += 1
        role = pr.role or ""
        if pr.person_id:
            edges.append(
                {
                    "id": f"e{eid}",
                    "fromNode": f"case_{pr.case_id}",
                    "fromSide": "bottom",
                    "toNode": f"person_{pr.person_id}",
                    "toSide": "top",
                    "color": COLORS["person"],
                    "label": role,
                }
            )
        elif pr.org_id:
            edges.append(
                {
                    "id": f"e{eid}",
                    "fromNode": f"case_{pr.case_id}",
                    "fromSide": "bottom",
                    "toNode": f"org_{pr.org_id}",
                    "toSide": "top",
                    "color": COLORS["org"],
                    "label": role,
                }
            )

    return {"nodes": nodes, "edges": edges}


async def build_once(Session, out_path: str) -> tuple:
    async with Session() as session:
        state = await fetch_state(session)
        fingerprint = await fetch_fingerprint(session)
    canvas = build_canvas(*state)
    import json

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(canvas, f, ensure_ascii=False)
    print(
        f"[legal-canvas] {len(canvas['nodes'])} nodes "
        f"({len(state[0])} cases, {len(state[1])} laws, {len(state[2])} people, {len(state[3])} orgs), "
        f"{len(canvas['edges'])} edges -> {out_path}"
    )
    return fingerprint


async def main(out_path: str, watch: bool, interval: int) -> None:
    engine = create_async_engine(resolve_database_url())
    Session = async_sessionmaker(engine, expire_on_commit=False)

    last_fp = await build_once(Session, out_path)
    if not watch:
        return

    print(f"[legal-canvas] watching for changes every {interval}s (Ctrl+C to stop)")
    while True:
        time.sleep(interval)
        async with Session() as session:
            fp = await fetch_fingerprint(session)
        if fp != last_fp:
            last_fp = await build_once(Session, out_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--watch", action="store_true", help="keep running, rebuild whenever row counts change")
    parser.add_argument("--interval", type=int, default=15, help="seconds between checks in --watch mode")
    args = parser.parse_args()
    asyncio.run(main(args.out, args.watch, args.interval))

"""
The knowledge graph: (src) -[relation]-> (dst) over cases, entries, documents,
persons, organizations, laws and labels.

`graph_edges` is the flattened form of the typed relations (`case_parties`,
`case_references`, `entries.case_id`, …). The typed tables stay the relational
truth; this table exists so a neighbourhood walk of any node is a single
indexed scan, so the UI can draw a case or a lawyer as a picture, and so the
whole thing exports to a real graph database (`to_cypher`) unchanged.

Node types: case | entry | document | person | org | law | label
Relations : HAS_ENTRY | HAS_DOCUMENT | PARTY | REPRESENTS | CITES | LABELED |
            SIMILAR_TO | HEARD_AT
"""

from __future__ import annotations

from sqlalchemy import delete, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Document, Entry, GraphEdge, LegalCase, LegalReference, Organization, Person,
)

NODE_FA = {
    "case": "پرونده", "entry": "مدخل", "document": "سند", "person": "شخص",
    "org": "سازمان", "law": "مادهٔ قانونی", "label": "برچسب",
}
RELATION_FA = {
    "HAS_ENTRY": "دارای مدخل", "HAS_DOCUMENT": "دارای سند", "PARTY": "طرف پرونده",
    "REPRESENTS": "وکالت", "CITES": "استناد به", "LABELED": "برچسب",
    "SIMILAR_TO": "مشابه", "HEARD_AT": "مرجع رسیدگی",
}


async def link(
    session: AsyncSession, src_type: str, src_id, relation: str, dst_type: str, dst_id,
    *, weight: float = 1.0, meta: dict | None = None,
) -> None:
    """Idempotent edge insert."""
    stmt = insert(GraphEdge).values(
        src_type=src_type, src_id=str(src_id), relation=relation,
        dst_type=dst_type, dst_id=str(dst_id), weight=weight, meta=meta or {},
    ).on_conflict_do_update(
        index_elements=["src_type", "src_id", "relation", "dst_type", "dst_id"],
        set_={"weight": weight, "meta": meta or {}},
    )
    await session.execute(stmt)


async def unlink_node(session: AsyncSession, node_type: str, node_id) -> None:
    """Drop every edge touching a node (before re-syncing it)."""
    nid = str(node_id)
    await session.execute(delete(GraphEdge).where(or_(
        (GraphEdge.src_type == node_type) & (GraphEdge.src_id == nid),
        (GraphEdge.dst_type == node_type) & (GraphEdge.dst_id == nid),
    )))


async def edges_of(session: AsyncSession, node_type: str, node_id, *, limit: int = 400) -> list[GraphEdge]:
    nid = str(node_id)
    rows = (await session.execute(
        select(GraphEdge).where(or_(
            (GraphEdge.src_type == node_type) & (GraphEdge.src_id == nid),
            (GraphEdge.dst_type == node_type) & (GraphEdge.dst_id == nid),
        )).limit(limit)
    )).scalars().all()
    return list(rows)


async def _labels_for(session: AsyncSession, nodes: dict[tuple[str, str], dict]) -> None:
    """Fill `label` (display text) for every node id in place — one query per type."""
    by_type: dict[str, list[str]] = {}
    for (ntype, nid) in nodes:
        by_type.setdefault(ntype, []).append(nid)

    def _uuid_list(ids):
        import uuid
        out = []
        for x in ids:
            try:
                out.append(uuid.UUID(str(x)))
            except ValueError:
                continue
        return out

    if "case" in by_type:
        for c in (await session.execute(
            select(LegalCase.id, LegalCase.case_number, LegalCase.title, LegalCase.case_type,
                   LegalCase.insurance_line, LegalCase.status)
            .where(LegalCase.id.in_(_uuid_list(by_type["case"])))
        )).all():
            nodes[("case", str(c.id))].update({
                "label": c.title or c.case_number, "case_number": c.case_number,
                "case_type": c.case_type, "insurance_line": c.insurance_line, "status": c.status,
            })
    if "entry" in by_type:
        for e in (await session.execute(
            select(Entry.id, Entry.title, Entry.kind).where(Entry.id.in_(_uuid_list(by_type["entry"])))
        )).all():
            nodes[("entry", str(e.id))].update({"label": e.title or "مدخل", "kind": e.kind})
    if "document" in by_type:
        for d in (await session.execute(
            select(Document.id, Document.title, Document.source)
            .where(Document.id.in_(_uuid_list(by_type["document"])))
        )).all():
            nodes[("document", str(d.id))].update({"label": d.title or d.source, "source": d.source})
    if "person" in by_type:
        for p in (await session.execute(
            select(Person.id, Person.name, Person.roles).where(Person.id.in_(_uuid_list(by_type["person"])))
        )).all():
            nodes[("person", str(p.id))].update({"label": p.name, "roles": p.roles or []})
    if "org" in by_type:
        for o in (await session.execute(
            select(Organization.id, Organization.name, Organization.kind)
            .where(Organization.id.in_(_uuid_list(by_type["org"])))
        )).all():
            nodes[("org", str(o.id))].update({"label": o.name, "kind": o.kind})
    if "law" in by_type:
        for l in (await session.execute(
            select(LegalReference.id, LegalReference.law_title, LegalReference.article_no,
                   LegalReference.title, LegalReference.kind)
            .where(LegalReference.id.in_(_uuid_list(by_type["law"])))
        )).all():
            art = f" — مادهٔ {l.article_no}" if l.article_no else ""
            nodes[("law", str(l.id))].update({
                "label": f"{l.law_title}{art}", "title": l.title, "kind": l.kind,
            })
    for (ntype, nid), node in nodes.items():
        node.setdefault("label", nid if ntype == "label" else f"{NODE_FA.get(ntype, ntype)} {nid[:8]}")


async def neighborhood(
    session: AsyncSession, node_type: str, node_id, *, depth: int = 1,
    max_nodes: int = 120, skip_types: tuple[str, ...] = (),
) -> dict:
    """Breadth-first walk from a node. Returns {nodes, edges} with display labels.

    `depth=1` is a case or a person with everything directly attached; `depth=2`
    from a lawyer reaches the laws their cases cite. `skip_types` keeps hubs
    (a label shared by 60 cases) from exploding the picture.
    """
    start = (node_type, str(node_id))
    nodes: dict[tuple[str, str], dict] = {start: {"type": node_type, "id": str(node_id), "root": True}}
    edges: dict[tuple, dict] = {}
    frontier = [start]
    for _level in range(depth):
        next_frontier: list[tuple[str, str]] = []
        for (ntype, nid) in frontier:
            for edge in await edges_of(session, ntype, nid):
                key = (edge.src_type, edge.src_id, edge.relation, edge.dst_type, edge.dst_id)
                if key in edges:
                    continue
                edges[key] = {
                    "src": {"type": edge.src_type, "id": edge.src_id},
                    "relation": edge.relation, "relation_fa": RELATION_FA.get(edge.relation, edge.relation),
                    "dst": {"type": edge.dst_type, "id": edge.dst_id},
                    "weight": edge.weight, "meta": edge.meta or {},
                }
                for other in ((edge.src_type, edge.src_id), (edge.dst_type, edge.dst_id)):
                    if other not in nodes:
                        nodes[other] = {"type": other[0], "id": other[1]}
                        if other[0] not in skip_types and len(nodes) < max_nodes:
                            next_frontier.append(other)
            if len(nodes) >= max_nodes:
                break
        frontier = next_frontier
        if not frontier:
            break
    await _labels_for(session, nodes)
    return {"root": {"type": node_type, "id": str(node_id)},
            "nodes": list(nodes.values()), "edges": list(edges.values())}


async def whole(
    session: AsyncSession, *, types: tuple[str, ...] = (), limit: int = 20000,
) -> dict:
    """The entire graph, not a walk from one node — the export path.

    `neighborhood()` answers "what is around this record"; this answers "what is
    in the archive", which is what a dump to Cypher or to a vault needs.
    `types` keeps the edge to those whose *both* ends are wanted, so asking for
    cases and laws does not drag every entry and document along with them.
    """
    rows = list((await session.scalars(select(GraphEdge).limit(limit))).all())
    nodes: dict[tuple[str, str], dict] = {}
    edges: list[dict] = []
    for edge in rows:
        if types and (edge.src_type not in types or edge.dst_type not in types):
            continue
        edges.append({
            "src": {"type": edge.src_type, "id": edge.src_id},
            "relation": edge.relation, "relation_fa": RELATION_FA.get(edge.relation, edge.relation),
            "dst": {"type": edge.dst_type, "id": edge.dst_id},
            "weight": edge.weight, "meta": edge.meta or {},
        })
        for other in ((edge.src_type, edge.src_id), (edge.dst_type, edge.dst_id)):
            nodes.setdefault(other, {"type": other[0], "id": other[1]})
    await _labels_for(session, nodes)
    return {"nodes": list(nodes.values()), "edges": edges}


# --------------------------------------------------------------------------- #
# Renderers
# --------------------------------------------------------------------------- #
_DOT_STYLE = {
    "case": ('box', '#f4e4bc', '#8a6d1f'),
    "entry": ('note', '#eef2f7', '#4a5568'),
    "document": ('folder', '#e8eef5', '#4a5568'),
    "person": ('ellipse', '#dbeafe', '#1e40af'),
    "org": ('component', '#dcfce7', '#166534'),
    "law": ('tab', '#fde2e2', '#991b1b'),
    "label": ('plaintext', '#ffffff', '#6b7280'),
}


def _esc(text: str) -> str:
    return str(text or "").replace('"', '\\"').replace("\n", " ")


def to_dot(graph: dict, *, rankdir: str = "LR") -> str:
    """Graphviz source for `st.graphviz_chart` (rendered client-side, no binary)."""
    lines = [
        f'digraph G {{ rankdir={rankdir}; graph [fontname="Vazirmatn, Tahoma", nodesep=0.35, ranksep=0.6];',
        'node [fontname="Vazirmatn, Tahoma", fontsize=11, style="filled,rounded", penwidth=1];',
        'edge [fontname="Vazirmatn, Tahoma", fontsize=9, color="#9aa3af", fontcolor="#6b7280"];',
    ]
    for n in graph["nodes"]:
        shape, fill, color = _DOT_STYLE.get(n["type"], ("ellipse", "#fff", "#333"))
        label = _esc(n.get("label", n["id"]))
        if len(label) > 48:
            label = label[:46] + "…"
        pen = 2.4 if n.get("root") else 1
        lines.append(
            f'"{n["type"]}:{n["id"]}" [label="{label}", shape={shape}, fillcolor="{fill}", '
            f'color="{color}", penwidth={pen}];'
        )
    for e in graph["edges"]:
        lab = e.get("relation_fa") or e["relation"]
        role = (e.get("meta") or {}).get("role_fa") or (e.get("meta") or {}).get("role")
        if role:
            lab = f"{lab}: {role}"
        lines.append(
            f'"{e["src"]["type"]}:{e["src"]["id"]}" -> "{e["dst"]["type"]}:{e["dst"]["id"]}" '
            f'[label="{_esc(lab)}"];'
        )
    lines.append("}")
    return "\n".join(lines)


def to_cypher(graph: dict) -> str:
    """Neo4j-loadable statements for the same picture — the export path to a
    dedicated graph database, when one is wanted."""
    out = []
    for n in graph["nodes"]:
        props = {k: v for k, v in n.items() if k not in ("type", "root") and isinstance(v, (str, int, float))}
        prop_s = ", ".join(f'{k}: "{_esc(v)}"' for k, v in props.items())
        out.append(f'MERGE (:{n["type"].capitalize()} {{{prop_s}}});')
    for e in graph["edges"]:
        out.append(
            f'MATCH (a:{e["src"]["type"].capitalize()} {{id: "{e["src"]["id"]}"}}), '
            f'(b:{e["dst"]["type"].capitalize()} {{id: "{e["dst"]["id"]}"}}) '
            f'MERGE (a)-[:{e["relation"]}]->(b);'
        )
    return "\n".join(out)

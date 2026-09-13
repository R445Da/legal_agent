"""
Read the archive folder of the Obsidian vault back as a graph.

This is the input to section ۲۰. It parses exactly what Obsidian parses — the
`---` frontmatter, the `[[wikilinks]]`, the `#tags` — so the picture the app
draws and the picture Obsidian draws come from the same files. Editing a note
by hand in Obsidian therefore shows up in the app on the next refresh, which is
the whole point of routing through the vault rather than querying the database
a second time.

Nothing here touches the database, and nothing outside `آرشیو/` is read: the
same vault holds a thousand notes graphify wrote about the source code, and
those must stay out of the graph.
"""

from __future__ import annotations

import re

from app.rag.vaultsync import ARCHIVE_DIR, FOLDERS, archive_path, obsidian_uri, vault_exists

_WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:\|[^\]]*)?\]\]")
_LINK_LINE = re.compile(r"^-\s*\[\[([^\]|#]+)(?:\|[^\]]*)?\]\]\s*(?:—\s*(.*))?$")

# Which tag namespace decides a node's colour. `موضوع` (facet) wins over
# `برچسب` (the extractor's free tags) because facets are a closed vocabulary
# and therefore produce stable clusters.
_COLOUR_NAMESPACES = ("موضوع", "برچسب")

_KIND_BY_FOLDER = {folder: kind for kind, folder in FOLDERS.items()}


def _parse_front(text: str) -> tuple[dict, list[str], str]:
    """`(frontmatter, tags, body)` — a deliberately small YAML subset, since
    this only ever reads notes `vaultsync` wrote."""
    if not text.startswith("---"):
        return {}, [], text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, [], text
    head, body = text[3:end], text[end + 4:]
    front: dict = {}
    tags: list[str] = []
    in_tags = False
    for line in head.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if in_tags and stripped.startswith("- "):
            tags.append(stripped[2:].strip())
            continue
        in_tags = False
        if stripped == "tags:":
            in_tags = True
            continue
        if ":" in stripped:
            key, _, value = stripped.partition(":")
            front[key.strip()] = value.strip().strip('"')
    return front, tags, body


def _primary_tag(tags: list[str]) -> str | None:
    """The tag a node is coloured by: the most specific facet it carries."""
    for namespace in _COLOUR_NAMESPACES:
        for tag in tags:
            parts = tag.split("/")
            if len(parts) >= 3 and parts[1] == namespace:
                return "/".join(parts[1:])
    return None


def load() -> dict:
    """`{"nodes": [...], "edges": [...], "tags": [...]}` for the whole archive.

    Returns empty lists when there is no vault — CI and the Docker image never
    have one, and section ۲۰ has to render an empty state rather than crash.
    """
    if not vault_exists():
        return {"nodes": [], "edges": [], "tags": [], "vault": None}

    root = archive_path()
    if not root.is_dir():
        return {"nodes": [], "edges": [], "tags": [], "vault": str(root.parent)}

    nodes: dict[str, dict] = {}
    raw_links: list[tuple[str, str, str]] = []

    for path in sorted(root.rglob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        front, tags, body = _parse_front(text)
        folder = path.parent.name
        kind = _KIND_BY_FOLDER.get(folder) or front.get("type") or "note"
        name = path.stem
        relpath = f"{ARCHIVE_DIR}/{path.relative_to(root).as_posix()}"

        nodes[name] = {
            "id": name,
            "name": name,
            "kind": kind,
            "tags": tags,
            "tag": _primary_tag(tags),
            "record_id": front.get("id") or "",
            "case_number": front.get("case_number") or "",
            "relpath": relpath,
            "uri": obsidian_uri(relpath),
            "degree": 0,
        }

        for line in body.splitlines():
            match = _LINK_LINE.match(line.strip())
            if match:
                raw_links.append((name, match.group(1).strip(), (match.group(2) or "").strip()))
            elif "[[" in line:
                for target in _WIKILINK.findall(line):
                    raw_links.append((name, target.strip(), ""))

    edges = []
    seen: set[tuple[str, str]] = set()
    for source, target, caption in raw_links:
        if target not in nodes or source == target:
            continue            # a link to a code note, or to a note not exported
        key = (source, target)
        if key in seen:
            continue
        seen.add(key)
        edges.append({"source": source, "target": target, "caption": caption})
        nodes[source]["degree"] += 1
        nodes[target]["degree"] += 1

    _inherit_tags(nodes, edges)

    counts: dict[str, int] = {}
    for node in nodes.values():
        if node["tag"]:
            counts[node["tag"]] = counts.get(node["tag"], 0) + 1
    tags = [{"tag": t, "nodes": n} for t, n in sorted(counts.items(), key=lambda kv: -kv[1])]

    return {
        "nodes": list(nodes.values()),
        "edges": edges,
        "tags": tags,
        "vault": str(root.parent),
    }


def _inherit_tags(nodes: dict, edges: list) -> None:
    """A law or a person carries no tag of its own, so it takes the commonest
    tag among the cases it is linked to. Without this every node that is not a
    case would be grey and the clusters would be half empty."""
    votes: dict[str, dict[str, int]] = {}
    for edge in edges:
        for a, b in ((edge["source"], edge["target"]), (edge["target"], edge["source"])):
            tag = nodes[a]["tag"]
            if tag and not nodes[b]["tag"]:
                votes.setdefault(b, {})
                votes[b][tag] = votes[b].get(tag, 0) + 1
    for name, tally in votes.items():
        nodes[name]["tag"] = max(tally.items(), key=lambda kv: kv[1])[0]
        nodes[name]["inherited"] = True

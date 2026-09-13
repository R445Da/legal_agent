"""
The archive as an Obsidian vault: one markdown note per record.

Obsidian's graph view draws *notes* and the links between them — a `.canvas`
file (`scripts/build_legal_canvas.py`) is invisible to it. So the database only
appears in the user's graph once every case, law, person and organization is a
real note with `[[wikilinks]]` and `#tags`. That is what this module writes.

It writes **only** inside `<vault>/آرشیو/`. The vault it targets is the one the
user already has open, which also holds a thousand notes graphify wrote about
the source code; nothing outside the archive folder is read, moved or modified,
and `.obsidian/` settings are never touched.

The same folder is the input to section ۲۰ (`app/rag/vaultmap.py`), so the
in-app graph and Obsidian's own graph are two renderings of one set of files.

    python -m scripts.export_vault            # backfill everything
    python -m scripts.export_vault --watch    # and keep it in sync
"""

from __future__ import annotations

import os
import pathlib
import re
import urllib.parse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    CaseParty, CaseReference, Entry, LegalCase, LegalReference, Organization, Person,
)
# The role codes in `case_parties.role`, translated the way the case and
# editor views already translate them. A second copy here would drift the
# moment a role is added.
from app.rag.casebase import ROLE_FA

# The vault the user has open. `VAULT_DIR` overrides it for anyone whose vault
# lives elsewhere; the default is the graphify output folder in this repo.
VAULT_DIR = os.environ.get(
    "VAULT_DIR",
    str(pathlib.Path(__file__).resolve().parents[2] / "graphify-out" / "obsidian"),
)

# Everything this module writes lives under here, and nothing else does.
ARCHIVE_DIR = "آرشیو"

FOLDERS = {
    "case": "پرونده‌ها",
    "law": "قوانین",
    "person": "اشخاص",
    "org": "سازمان‌ها",
    "entry": "مدخل‌ها",
}

# Persian tag stems. Obsidian tags cannot contain spaces, so `_tag()` folds
# them out — see below.
TAG_ROOT = "آرشیو"


def vault_path() -> pathlib.Path:
    return pathlib.Path(VAULT_DIR).expanduser()


def archive_path() -> pathlib.Path:
    return vault_path() / ARCHIVE_DIR


def vault_exists() -> bool:
    """A vault is a folder; without one there is nothing to read or write.

    Callers use this instead of letting a missing folder raise, because CI and
    the Docker image never have one — `graphify-out/` is gitignored.
    """
    return vault_path().is_dir()


# --------------------------------------------------------------------------- #
# Names
# --------------------------------------------------------------------------- #
# Obsidian resolves `[[a link]]` by note *basename*, so basenames have to be
# unique across the archive and free of the characters a filesystem rejects.
_ILLEGAL = re.compile(r'[\\/:*?"<>|\[\]#^]')


def note_name(text: str, *, fallback: str = "بدون‌عنوان") -> str:
    """A filesystem- and wikilink-safe basename."""
    name = _ILLEGAL.sub("", str(text or "")).replace("\n", " ").strip()
    name = re.sub(r"\s+", " ", name)
    return (name[:80].strip() or fallback)


# An Obsidian tag may hold letters, digits, `_`, `-` and `/` and nothing else.
# A tag with a bracket or a full stop in it — «رجوع تأمین اجتماعی (م. ۶۶)» is a real
# one in this archive — is silently truncated at the first bad character, which
# would split one cluster into several.
_TAG_ILLEGAL = re.compile(r"[^\w\u0600-\u06FF-]+", re.UNICODE)


def _tag(*parts: str) -> str:
    """`#آرشیو/موضوع/بیمه-شخص-ثالث` — one path segment per part, nothing Obsidian rejects."""
    clean = []
    for part in parts:
        p = _TAG_ILLEGAL.sub("-", str(part or "").strip())
        p = re.sub(r"-{2,}", "-", p).strip("-")
        if p:
            clean.append(p)
    return "/".join(clean)


def obsidian_uri(relpath: str) -> str:
    """`obsidian://open?...` for a note, so the app can jump into real Obsidian."""
    vault = vault_path().name
    return (
        "obsidian://open?vault=" + urllib.parse.quote(vault)
        + "&file=" + urllib.parse.quote(str(relpath))
    )


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #
def _yaml_value(value) -> str:
    if value is None:
        return '""'
    text = str(value).replace('"', "'").replace("\n", " ").strip()
    return f'"{text}"'


def render_note(*, kind: str, name: str, front: dict, body: str,
                links: list[tuple[str, str]], tags: list[str]) -> str:
    """One note: frontmatter, a body, a links section, a tag footer.

    `links` is `[(target basename, caption)]` and becomes the `## پیوندها`
    list — these are what Obsidian's graph actually draws edges from, and what
    `vaultmap.parse` reads back.
    """
    lines = ["---", f"type: {kind}"]
    for key, value in front.items():
        lines.append(f"{key}: {_yaml_value(value)}")
    if tags:
        lines.append("tags:")
        lines.extend(f"  - {t}" for t in tags)
    lines.append("---")
    lines.append("")
    lines.append(f"# {name}")
    lines.append("")
    if body.strip():
        lines.append(body.strip())
        lines.append("")
    if links:
        lines.append("## پیوندها")
        for target, caption in links:
            lines.append(f"- [[{target}]] — {caption}" if caption else f"- [[{target}]]")
        lines.append("")
    if tags:
        lines.append(" ".join(f"#{t}" for t in tags))
        lines.append("")
    return "\n".join(lines)


def _write(path: pathlib.Path, text: str) -> bool:
    """Write only when the content actually changed.

    Obsidian reloads a note whenever its file's mtime moves, so rewriting
    identical bytes on every export would make the user's open note flicker and
    would defeat `--watch`'s whole purpose.
    """
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


# --------------------------------------------------------------------------- #
# Building the notes from the database
# --------------------------------------------------------------------------- #
async def _fetch(session: AsyncSession) -> dict:
    async def rows(model):
        return list((await session.scalars(select(model))).all())

    return {
        "cases": await rows(LegalCase),
        "laws": await rows(LegalReference),
        "persons": await rows(Person),
        "orgs": await rows(Organization),
        "parties": await rows(CaseParty),
        "citations": await rows(CaseReference),
        "entries": await rows(Entry),
    }


def _law_name(r) -> str:
    article = f" — ماده {r.article_no}" if r.article_no else ""
    return note_name(f"{r.law_title or 'قانون'}{article}")


def _case_name(c) -> str:
    title = (c.title or "").strip()
    return note_name(f"{c.case_number} {title}".strip() if title else str(c.case_number))


def _unique(names: dict) -> None:
    """Two records can share a display name; Obsidian cannot. Suffix duplicates."""
    seen: dict[str, int] = {}
    for key, name in list(names.items()):
        lowered = name.casefold()
        if lowered in seen:
            seen[lowered] += 1
            names[key] = f"{name} ({seen[lowered]})"
        else:
            seen[lowered] = 1


def build_notes(state: dict) -> list[dict]:
    """Every note as `{kind, name, relpath, text}` — pure, so it is testable
    without a vault on disk."""
    cases, laws = state["cases"], state["laws"]
    persons, orgs = state["persons"], state["orgs"]

    names: dict[tuple[str, str], str] = {}
    for c in cases:
        names[("case", str(c.id))] = _case_name(c)
    for r in laws:
        names[("law", str(r.id))] = _law_name(r)
    for p in persons:
        names[("person", str(p.id))] = note_name(p.name)
    for o in orgs:
        names[("org", str(o.id))] = note_name(o.name)
    _unique(names)

    # Tags per case: the extractor's own tags on its entries, plus the two
    # structured facets that behave like tags in practice.
    case_tags: dict[str, list[str]] = {}
    case_entries: dict[str, list] = {}
    for e in state["entries"]:
        if not e.case_id:
            continue
        cid = str(e.case_id)
        case_entries.setdefault(cid, []).append(e)
        for tag in (e.tags or []):
            if isinstance(tag, str) and tag.strip():
                case_tags.setdefault(cid, [])
                if tag.strip() not in case_tags[cid]:
                    case_tags[cid].append(tag.strip())

    # Edges, grouped by the case they hang off.
    parties_by_case: dict[str, list] = {}
    for p in state["parties"]:
        parties_by_case.setdefault(str(p.case_id), []).append(p)
    cites_by_case: dict[str, list] = {}
    for c in state["citations"]:
        cites_by_case.setdefault(str(c.case_id), []).append(c)

    notes: list[dict] = []

    def rel(kind: str, name: str) -> str:
        return f"{ARCHIVE_DIR}/{FOLDERS[kind]}/{name}.md"

    for c in cases:
        cid = str(c.id)
        name = names[("case", cid)]
        tags = [_tag(TAG_ROOT, "پرونده")]
        for facet in (c.insurance_line, c.case_type):
            if facet:
                tags.append(_tag(TAG_ROOT, "موضوع", facet))
        for tag in case_tags.get(cid, []):
            tags.append(_tag(TAG_ROOT, "برچسب", tag))

        links: list[tuple[str, str]] = []
        for party in parties_by_case.get(cid, []):
            role = ROLE_FA.get(party.role, party.role or "طرف پرونده")
            key = ("person", str(party.person_id)) if party.person_id else ("org", str(party.org_id))
            if key[1] and key in names:
                links.append((names[key], role))
        for cite in cites_by_case.get(cid, []):
            key = ("law", str(cite.ref_id))
            if key in names:
                links.append((names[key], f"استناد به — {cite.context}" if cite.context else "استناد به"))

        summaries = [e.summary for e in case_entries.get(cid, []) if e.summary]
        body = "\n\n".join(
            [s for s in [(c.outcome or "").strip()] if s]
            + [str(s).strip() for s in summaries[:3]]
        )
        notes.append({
            "kind": "case", "name": name, "relpath": rel("case", name),
            "text": render_note(
                kind="case", name=name, links=links, tags=tags, body=body,
                front={
                    "id": c.id, "case_number": c.case_number, "case_type": c.case_type,
                    "insurance_line": c.insurance_line, "court": c.court, "branch": c.branch,
                    "group": c.group, "status": c.status, "stage": c.stage,
                    "filed_date": c.filed_date, "decided_date": c.decided_date,
                },
            ),
        })

    for r in laws:
        name = names[("law", str(r.id))]
        tags = [_tag(TAG_ROOT, "قانون"), _tag(TAG_ROOT, "قانون", r.law_title or "")]
        notes.append({
            "kind": "law", "name": name, "relpath": rel("law", name),
            "text": render_note(
                kind="law", name=name, links=[], tags=[t for t in tags if t],
                body=((r.title or "") + "\n\n" + (r.text or "")).strip(),
                front={"id": r.id, "law_title": r.law_title, "article_no": r.article_no,
                       "law_year": r.law_year, "ref_key": r.ref_key},
            ),
        })

    for p in persons:
        name = names[("person", str(p.id))]
        roles = p.roles if isinstance(p.roles, list) else [p.roles] if p.roles else []
        tags = [_tag(TAG_ROOT, "شخص")] + [_tag(TAG_ROOT, "نقش", r) for r in roles if r]
        notes.append({
            "kind": "person", "name": name, "relpath": rel("person", name),
            "text": render_note(
                kind="person", name=name, links=[], tags=tags,
                body="نقش‌ها: " + ("، ".join(str(r) for r in roles) if roles else "—"),
                front={"id": p.id, "name": p.name},
            ),
        })

    for o in orgs:
        name = names[("org", str(o.id))]
        roles = o.roles if isinstance(o.roles, list) else [o.roles] if o.roles else []
        tags = [_tag(TAG_ROOT, "سازمان"), _tag(TAG_ROOT, "نوع-سازمان", o.kind or "")]
        notes.append({
            "kind": "org", "name": name, "relpath": rel("org", name),
            "text": render_note(
                kind="org", name=name, links=[], tags=[t for t in tags if t],
                body="نقش‌ها: " + ("، ".join(str(r) for r in roles) if roles else "—"),
                front={"id": o.id, "name": o.name, "kind": o.kind},
            ),
        })

    return notes


async def export_all(session: AsyncSession) -> dict:
    """Write the whole archive into the vault. Returns what changed."""
    notes = build_notes(await _fetch(session))
    root = vault_path()
    root.mkdir(parents=True, exist_ok=True)
    written = 0
    for note in notes:
        if _write(root / note["relpath"], note["text"]):
            written += 1
    return {"notes": len(notes), "written": written, "vault": str(root)}


async def fingerprint(session: AsyncSession) -> tuple:
    """Cheap change signal for `--watch`: row counts across the tables drawn."""
    from sqlalchemy import func

    out = []
    for model in (LegalCase, LegalReference, Person, Organization, CaseParty, CaseReference, Entry):
        out.append(await session.scalar(select(func.count()).select_from(model)))
    return tuple(out)

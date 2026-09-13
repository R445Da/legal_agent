"""
Proposing an edit to an entry — and never performing one.

Editing is the first thing in this system a chat message can do that changes
the archive, so the split matters: the model may work out *which* entry and
*which* field the user means, but the value that lands in the database is the
user's own words, and nothing here writes. A proposal is a plain dict showing
the current value beside the new one; only the confirmation step calls
`catalog.update_entry`, which is the single writer that re-syncs the case, the
persons and organizations, the citations and the graph.

Two shapes, because an entry's fields are not all scalars:

    propose_edit    replace a field       «شمارهٔ پرونده را به ۱۴۰۰۲۲۲ تغییر بده»
    propose_append  add to a list field   «یک رویداد به تایم‌لاینش اضافه کن»

`entities` is the odd one: it is a dict of facets (case number, court, topic),
so editing «شمارهٔ پرونده» is a merge into it rather than a replacement of it.
`update_entry` already merges `entities`, so a proposal only has to name the
facet.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.rag import catalog

# The scalar and list fields a chat edit may touch, with the Persian names the
# user actually says. `raw_text` is deliberately absent: rewriting the source
# text of a filed record from a chat line is not an edit, it is a re-filing.
FIELD_FA = {
    "title": "عنوان",
    "summary": "خلاصه",
    "kind": "نوع",
    "tags": "برچسب‌ها",
    "events": "رویدادها",
    "parties": "طرفین",
    "representation": "وکالت",
    "legal_refs": "مستندات قانونی",
}

# Facets inside `entities`, addressed by name.
FACET_FA = {
    "case_number": "شمارهٔ پرونده",
    "court": "مرجع رسیدگی",
    "topic": "موضوع",
    "people": "اشخاص",
    "orgs": "سازمان‌ها",
}

LIST_FIELDS = ("tags", "events", "parties", "representation", "legal_refs")

_FA_TO_FIELD = {fa: key for key, fa in FIELD_FA.items()}
_FA_TO_FACET = {fa: key for key, fa in FACET_FA.items()}


class EditError(ValueError):
    """A proposal that cannot be built — an unknown field, a missing entry."""


def resolve_field(name: str) -> tuple[str, str | None]:
    """`("entities", "case_number")` for «شمارهٔ پرونده», `("title", None)` for
    «عنوان». Accepts the English key too, so a model that answers in either
    vocabulary works."""
    key = str(name or "").strip()
    if key in FIELD_FA:
        return key, None
    if key in FACET_FA:
        return "entities", key
    if key in _FA_TO_FIELD:
        return _FA_TO_FIELD[key], None
    if key in _FA_TO_FACET:
        return "entities", _FA_TO_FACET[key]
    raise EditError(
        f"فیلد «{key}» قابل ویرایش نیست. فیلدهای مجاز: "
        + "، ".join(list(FIELD_FA.values()) + list(FACET_FA.values()))
    )


def _current(entry: dict, field: str, facet: str | None):
    if facet:
        return (entry.get("entities") or {}).get(facet, "")
    return entry.get(field)


def _as_text(value) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                parts.append(item.get("title") or item.get("name")
                             or item.get("description") or item.get("law") or str(item))
            else:
                parts.append(str(item))
        return "، ".join(p for p in parts if p) or "—"
    return str(value)


async def propose_edit(session: AsyncSession, entry_id: str, field: str, value) -> dict:
    """Replace a field. Returns the proposal; writes nothing."""
    entry = await catalog.get_entry(session, entry_id)
    if entry is None:
        raise EditError("مدخلی با این شناسه یافت نشد.")

    key, facet = resolve_field(field)
    old = _current(entry, key, facet)

    if key in LIST_FIELDS and not isinstance(value, list):
        # «برچسب‌ها را به الف، ب تغییر بده» — a list field set from one line.
        value = [v.strip() for v in str(value).replace("،", ",").split(",") if v.strip()]

    patch = {"entities": {facet: value}} if facet else {key: value}
    return {
        "entry_id": str(entry["id"]),
        "entry_title": entry.get("title") or "",
        "field": key,
        "facet": facet,
        "field_fa": FACET_FA[facet] if facet else FIELD_FA[key],
        "old": old,
        "old_text": _as_text(old),
        "new": value,
        "new_text": _as_text(value),
        "patch": patch,
        "op": "edit",
    }


async def propose_append(session: AsyncSession, entry_id: str, field: str, item) -> dict:
    """Add one item to a list field, keeping what is already there.

    This is «یک رویداد به تایم‌لاینش اضافه کن». It reads the current list and
    proposes the whole list back with the item appended, because
    `update_entry` replaces a list field rather than merging it — proposing
    only the new item would silently delete the rest.
    """
    entry = await catalog.get_entry(session, entry_id)
    if entry is None:
        raise EditError("مدخلی با این شناسه یافت نشد.")

    key, facet = resolve_field(field)
    if facet or key not in LIST_FIELDS:
        raise EditError(
            f"«{FACET_FA.get(facet) or FIELD_FA.get(key)}» فهرست نیست؛ برای تغییر آن از ویرایش استفاده کنید."
        )

    current = list(entry.get(key) or [])
    if isinstance(item, str) and key == "events":
        # «۱۴۰۳/۰۵/۱۲ جلسهٔ کارشناسی» — a date at the head is the event's date.
        text = item.strip()
        date, _, rest = text.partition(" ")
        looks_like_date = any(ch.isdigit() for ch in date) and ("/" in date or "-" in date)
        item = ({"date": date, "description": rest.strip()} if looks_like_date and rest
                else {"date": "", "description": text})
    elif isinstance(item, str) and key in ("tags",):
        item = item.strip()

    proposed = current + [item]
    return {
        "entry_id": str(entry["id"]),
        "entry_title": entry.get("title") or "",
        "field": key,
        "facet": None,
        "field_fa": FIELD_FA[key],
        "old": current,
        "old_text": f"{len(current)} مورد",
        "new": proposed,
        "new_text": _as_text([item]),
        "patch": {key: proposed},
        "op": "append",
    }


async def apply(session: AsyncSession, proposal: dict) -> dict | None:
    """The only path from a proposal to the database. Called by the
    confirmation step, never by a tool and never by the model."""
    if not proposal or not proposal.get("entry_id") or not proposal.get("patch"):
        raise EditError("پیشنهاد ویرایش ناقص است.")
    return await catalog.update_entry(session, proposal["entry_id"], proposal["patch"])

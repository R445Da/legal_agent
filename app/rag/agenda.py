"""
Dated items a person puts on a case: a hearing to attend, a deadline, a
reminder to file something.

These live in the **same event stream as the extracted ones** —
`Entry.events`, the list the case timeline, ۰۴ رویدادها and the dashboard's
«آخرین رویدادها» all read. That is deliberate. A reminder kept in a separate
table would be a second answer to "what is happening on this case", and the
two would drift; putting it in the one stream means a note added here shows up
everywhere a case's dates show up, with no extra wiring.

What keeps them apart is `source`, which every event already carries:

    "استخراج"   pulled out of the document by the extractor
    "دستی"      typed by a person on this screen
    "یادآور"    typed by a person, and meant as something still to do

So nothing here invents a schema. It appends to a list that already exists, in
the shape the rest of the app already reads, and the model is not involved at
any point — a date someone typed is not something to infer.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.db.models import Entry

# `source` values that mean a person put this here rather than the extractor.
MANUAL = "دستی"
REMINDER = "یادآور"
MANUAL_SOURCES = (MANUAL, REMINDER)

SOURCE_FA = {
    "استخراج": "از متن سند",
    MANUAL: "افزودهٔ کاربر",
    REMINDER: "یادآور",
}


async def _entry_for_case(session: AsyncSession, case_id: str) -> Entry | None:
    """The entry a case's manual events are appended to.

    A case is every entry sharing a case number, so one is picked to hold them
    — the most recent, which is the one a person is most likely looking at.
    """
    try:
        parsed = uuid.UUID(str(case_id))
    except ValueError:
        parsed = None

    if parsed is not None:
        entry = await session.get(Entry, parsed)
        if entry is not None:
            return entry
        rows = (await session.execute(
            select(Entry).where(Entry.case_id == parsed).order_by(Entry.created_at.desc())
        )).scalars().all()
        if rows:
            return rows[0]

    # Fall back to matching the printed case number.
    rows = (await session.execute(
        select(Entry).order_by(Entry.created_at.desc()).limit(500)
    )).scalars().all()
    for entry in rows:
        if str((entry.entities or {}).get("case_number") or "") == str(case_id):
            return entry
    return None


async def add_event(
    session: AsyncSession, case_id: str, *, date: str, title: str,
    detail: str = "", reminder: bool = False,
) -> dict | None:
    """Put a dated item on a case. Returns the event, or None if no entry held it."""
    title = (title or "").strip()
    if not title:
        raise ValueError("عنوان رویداد خالی است")

    entry = await _entry_for_case(session, case_id)
    if entry is None:
        return None

    event = {
        "id": uuid.uuid4().hex[:12],
        "date": (date or "").strip(),
        "description": title,
        "detail": (detail or "").strip(),
        "source": REMINDER if reminder else MANUAL,
    }
    events = list(entry.events or [])
    events.append(event)
    entry.events = events
    # `events` is a JSON column; SQLAlchemy does not see an in-place append, so
    # the change has to be announced or the commit writes nothing.
    flag_modified(entry, "events")
    await session.commit()
    return event


async def remove_event(session: AsyncSession, case_id: str, event_id: str) -> bool:
    """Delete a manually added event. Extracted ones are left alone — they are
    what the document said, and this screen is not where that gets rewritten."""
    entry = await _entry_for_case(session, case_id)
    if entry is None:
        return False
    events = list(entry.events or [])
    kept = [
        e for e in events
        if not (str(e.get("id")) == str(event_id) and e.get("source") in MANUAL_SOURCES)
    ]
    if len(kept) == len(events):
        return False
    entry.events = kept
    flag_modified(entry, "events")
    await session.commit()
    return True


def is_manual(event: dict) -> bool:
    return (event or {}).get("source") in MANUAL_SOURCES

"""
Chat threads that outlive a browser tab, and the record each one is working on.

The chat used to be `st.session_state["chat"]` — a Python list belonging to one
tab. A reload lost the thread, the API could not see it, and nothing could be
searched or deleted. Individual answers were already durable in
`assistant_answers`, and the filing dialogue already persisted its turns in
`runs.state`; only the chat itself was missing a home. This is that home.

The part that earns its keep is `focus`. A conversation is usually *about*
something — an entry just filed, an entry just edited, a case just looked up —
and the next message says «نشانش بده» or «یک رویداد به تایم‌لاینش اضافه کن»
rather than naming it again. Any turn that touches a record sets the focus, so
those follow-ups resolve without a model call and without the user repeating
themselves.

Deliberately **no embeddings over turns**: recall across old conversations was
offered and declined, and it is the expensive half of the idea.
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conversation, Message

# What a title is trimmed to — the first question usually says what the thread
# is about better than anything we could generate, and generating one costs a
# model call for something the user reads once.
_TITLE_CHARS = 70

VALID_FOCUS_KINDS = ("entry", "case", "document", "person", "org")


def _uuid(value) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def conversation_dict(row: Conversation, *, messages: list | None = None) -> dict:
    out = {
        "id": str(row.id),
        "title": row.title or "گفتگوی بی‌عنوان",
        "source": row.source,
        "focus": row.focus or {},
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
    if messages is not None:
        out["messages"] = messages
    return out


def message_dict(row: Message) -> dict:
    return {
        "id": str(row.id),
        "role": row.role,
        "text": row.text or "",
        "intent": row.intent,
        "model": row.model,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        **(row.extra or {}),
    }


async def start(session: AsyncSession, *, title: str | None = None, source: str = "ui") -> dict:
    row = Conversation(title=(title or "").strip()[:_TITLE_CHARS] or None, source=source, focus={})
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return conversation_dict(row)


async def get(session: AsyncSession, conversation_id) -> dict | None:
    key = _uuid(conversation_id)
    if key is None:
        return None
    row = await session.get(Conversation, key)
    if row is None:
        return None
    turns = (await session.scalars(
        select(Message).where(Message.conversation_id == row.id).order_by(Message.created_at)
    )).all()
    return conversation_dict(row, messages=[message_dict(m) for m in turns])


async def recent(session: AsyncSession, *, limit: int = 30) -> list[dict]:
    """The thread list, newest activity first, each with its message count."""
    rows = (await session.execute(
        select(Conversation, func.count(Message.id))
        .outerjoin(Message, Message.conversation_id == Conversation.id)
        .group_by(Conversation.id)
        .order_by(Conversation.updated_at.desc())
        .limit(limit)
    )).all()
    out = []
    for row, count in rows:
        item = conversation_dict(row)
        item["messages"] = count
        out.append(item)
    return out


async def add_message(
    session: AsyncSession, conversation_id, *, role: str, text: str = "",
    intent: str | None = None, model: str | None = None, **extra,
) -> dict | None:
    """Append a turn. The first user turn also names the conversation."""
    key = _uuid(conversation_id)
    if key is None:
        return None
    convo = await session.get(Conversation, key)
    if convo is None:
        return None

    row = Message(
        conversation_id=convo.id, role=role, text=text or "",
        intent=intent, model=model,
        extra={k: v for k, v in extra.items() if v is not None},
    )
    session.add(row)

    if role == "user" and not convo.title:
        convo.title = (text or "").strip()[:_TITLE_CHARS] or None
    # Touch the thread so `recent()` orders by real activity; `onupdate` alone
    # does not fire when no column of the row itself changed.
    convo.updated_at = func.now()

    await session.commit()
    await session.refresh(row)
    return message_dict(row)


async def history(session: AsyncSession, conversation_id, *, limit: int = 12) -> list[dict]:
    """The last few turns, oldest first — what the model is shown so that
    «همان پرونده» means something."""
    key = _uuid(conversation_id)
    if key is None:
        return []
    rows = (await session.scalars(
        select(Message).where(Message.conversation_id == key)
        .order_by(Message.created_at.desc()).limit(limit)
    )).all()
    return [message_dict(m) for m in reversed(list(rows))]


async def set_focus(
    session: AsyncSession, conversation_id, *, kind: str, id, label: str = "",  # noqa: A002
) -> dict | None:
    """Record what this conversation is working on.

    Called by whatever touched the record — the edit gate, a roster answer, a
    filing that committed — so the next message can say «آن» and be understood.
    """
    key = _uuid(conversation_id)
    if key is None or kind not in VALID_FOCUS_KINDS:
        return None
    convo = await session.get(Conversation, key)
    if convo is None:
        return None
    convo.focus = {"kind": kind, "id": str(id), "label": str(label or "")}
    await session.commit()
    await session.refresh(convo)
    return convo.focus


async def get_focus(session: AsyncSession, conversation_id) -> dict | None:
    key = _uuid(conversation_id)
    if key is None:
        return None
    convo = await session.get(Conversation, key)
    focus = (convo.focus if convo else None) or {}
    return focus or None


async def clear_focus(session: AsyncSession, conversation_id) -> None:
    key = _uuid(conversation_id)
    if key is None:
        return
    convo = await session.get(Conversation, key)
    if convo is not None:
        convo.focus = {}
        await session.commit()


async def remove(session: AsyncSession, conversation_id) -> bool:
    """Delete a thread and its turns. `assistant_answers` rows survive with a
    null `conversation_id` — the answers and their provenance are the archive's
    record of what was asked, not the user's chat list."""
    key = _uuid(conversation_id)
    if key is None:
        return False
    result = await session.execute(delete(Conversation).where(Conversation.id == key))
    await session.commit()
    return bool(result.rowcount)


async def clear_all(session: AsyncSession) -> int:
    result = await session.execute(delete(Conversation))
    await session.commit()
    return int(result.rowcount or 0)

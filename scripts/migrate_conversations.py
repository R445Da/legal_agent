"""
One-off: add the chat tables and link answers to the thread they came from.

`create_schema()` CREATEs missing tables, so `conversations` / `messages`
appear on the next app start by themselves — but it never ALTERs an existing
one, and `assistant_answers` needs a new `conversation_id` column.

    python -m scripts.migrate_conversations

Idempotent. Safe to run repeatedly and safe to run before the app has ever
started (it calls `create_schema` itself).
"""

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.engine import create_schema, resolve_database_url

DDL = [
    # The thread an answer belongs to. Nullable: every answer written before
    # conversations existed has none, and deleting a thread must not delete
    # the archive's record of what was asked.
    "ALTER TABLE assistant_answers ADD COLUMN IF NOT EXISTS conversation_id uuid",
    "ALTER TABLE assistant_answers DROP CONSTRAINT IF EXISTS assistant_answers_conversation_id_fkey",
    "ALTER TABLE assistant_answers ADD CONSTRAINT assistant_answers_conversation_id_fkey "
    "FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE SET NULL",
]


async def main() -> None:
    engine = create_async_engine(resolve_database_url())
    await create_schema(engine)
    async with engine.begin() as conn:
        for statement in DDL:
            await conn.execute(text(statement))
    await engine.dispose()
    print("conversations / messages ready; assistant_answers.conversation_id added")


if __name__ == "__main__":
    asyncio.run(main())

"""
One-off: add the lexical (full-text) columns that hybrid retrieval needs.

`create_schema()` only CREATEs missing tables — it never ALTERs an existing
one — so this bridges an already-populated `chunks` table to the new
`Chunk.text_search` column without a full rebuild / re-ingest.

    python -m scripts.migrate_fts

Idempotent. After an embedding-model change you rebuild `.pgdata` anyway and
`create_all` emits the column itself, making this unnecessary.
"""

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.engine import resolve_database_url
from app.db.models import _ENTRY_TSVECTOR, TS_CONFIG

DDL = [
    f"""ALTER TABLE chunks ADD COLUMN IF NOT EXISTS text_search tsvector
        GENERATED ALWAYS AS (to_tsvector('{TS_CONFIG}', text)) STORED""",
    "CREATE INDEX IF NOT EXISTS ix_chunks_text_search ON chunks USING gin (text_search)",
    # The same treatment for `entries`, so relational questions ("which cases
    # involve X") are ranked by ts_rank_cd rather than matched with ILIKE.
    f"""ALTER TABLE entries ADD COLUMN IF NOT EXISTS text_search tsvector
        GENERATED ALWAYS AS ({_ENTRY_TSVECTOR}) STORED""",
    "CREATE INDEX IF NOT EXISTS ix_entries_text_search ON entries USING gin (text_search)",
]


async def main() -> None:
    engine = create_async_engine(resolve_database_url())
    async with engine.begin() as conn:
        for stmt in DDL:
            await conn.execute(text(stmt))
            print("ok:", " ".join(stmt.split())[:70], "…")
        for table in ("chunks", "entries"):
            n = await conn.scalar(
                text(f"SELECT count(*) FROM {table} WHERE text_search IS NOT NULL")
            )
            print(f"text_search populated for {n} {table}")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

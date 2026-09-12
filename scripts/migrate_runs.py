"""
One-off: add the pipeline-run tables and the richer `entries.related` column.

`create_schema()` CREATEs missing tables (so `runs` / `run_steps` also appear on
the next app start) but never ALTERs an existing one — this bridges an
already-populated `entries` table to `Entry.related` without a rebuild.

    python -m scripts.migrate_runs

Idempotent. Safe to run repeatedly and safe to run before the app has ever
started (it calls `create_schema` itself).
"""

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.engine import create_schema, resolve_database_url

DDL = [
    # Supersedes the bare `related_ids` list — keeps the linked records with a
    # score and the past outcome. Default so existing rows read back as [].
    "ALTER TABLE entries ADD COLUMN IF NOT EXISTS related jsonb NOT NULL DEFAULT '[]'::jsonb",
]


async def main() -> None:
    engine = create_async_engine(resolve_database_url())

    # Creates `runs` and `run_steps` if they are missing; touches nothing else.
    await create_schema(engine)
    print("ok: create_schema (runs, run_steps)")

    async with engine.begin() as conn:
        for stmt in DDL:
            await conn.execute(text(stmt))
            print("ok:", " ".join(stmt.split())[:80], "…")

        runs = await conn.scalar(text("SELECT count(*) FROM runs"))
        entries_related = await conn.scalar(
            text("SELECT count(*) FROM entries WHERE related <> '[]'::jsonb")
        )
        print(f"runs table ready ({runs} rows) · entries with related links: {entries_related}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

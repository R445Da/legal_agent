"""
Database connection setup.

resolve_database_url() returns a ready-to-use SQLAlchemy async URL. When
DATABASE_URL is "embedded" (the default), it starts a project-local
PostgreSQL instance with the `pgserver` package and ensures the pgvector
extension exists — no system Postgres, Docker, or root required. Both the
API process and the ingestion script call this; pgserver reference-counts
the server, so they share one instance.
"""

import os
import pathlib

from app.config import settings

_ASYNC_PREFIX = "postgresql+asyncpg://"


def resolve_database_url() -> str:
    url = settings.database_url

    if url and url != "embedded":
        # Caller supplied a real URL; make sure it uses the async driver.
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", _ASYNC_PREFIX, 1)
        return url

    import pgserver

    data_dir = pathlib.Path(settings.pg_data_dir).absolute()
    data_dir.mkdir(parents=True, exist_ok=True)

    server = pgserver.get_server(data_dir)
    server.psql("CREATE EXTENSION IF NOT EXISTS vector;")

    # e.g. postgresql://postgres:@/postgres?host=/abs/path/.pgdata
    return server.get_uri().replace("postgresql://", _ASYNC_PREFIX, 1)


class EmbeddingMismatch(RuntimeError):
    """The stored vectors were written by a different embedding model."""


_FINGERPRINT_KEY = "embedding_fingerprint"


def _fingerprint() -> str:
    from app.config import settings
    from app.db.models import EMBEDDING_DIM

    prefixes = os.environ.get("EMBEDDING_PREFIXES", "1") != "0"
    return f"{settings.embedding_model}|dim={EMBEDDING_DIM}|prefixes={int(prefixes)}"


async def check_embeddings(engine) -> str | None:
    """Refuse to run against vectors a different embedding model produced.

    This is the only misconfiguration in the system that yields *wrong answers*
    rather than an error. Two 384-dim models both fit `Vector(384)` and both
    insert cleanly, but their coordinate spaces are unrelated — so cosine
    distance between a query from model A and a chunk from model B is noise.
    Retrieval silently returns the wrong documents and the LLM dutifully
    summarises them.

    A dimension change at least fails loudly (the column rejects the insert).
    A same-dimension model swap is the silent one, and that is what this
    catches: the fingerprint is written next to the data the first time
    anything is embedded, and compared on every startup after.

    Returns a message when it recorded or refreshed the fingerprint, else None.
    """
    from sqlalchemy import func, select
    from sqlalchemy.dialects.postgresql import insert
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models import Chunk, Meta

    current = _fingerprint()
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as session:
        stored = await session.scalar(
            select(Meta.value).where(Meta.key == _FINGERPRINT_KEY)
        )
        chunks = await session.scalar(select(func.count()).select_from(Chunk)) or 0

        if stored == current:
            return None

        # Nothing embedded yet, or an older database from before this check —
        # adopt the current configuration as the truth rather than guessing.
        if stored is None or chunks == 0:
            await session.execute(
                insert(Meta)
                .values(key=_FINGERPRINT_KEY, value=current)
                .on_conflict_do_update(index_elements=["key"], set_={"value": current})
            )
            await session.commit()
            if chunks == 0:
                return f"embedding fingerprint recorded: {current}"
            return (
                f"embedding fingerprint adopted for {chunks} existing chunks: "
                f"{current} — if these were embedded with a different model, "
                "re-ingest now."
            )

        raise EmbeddingMismatch(
            "Embedding model changed, but the stored vectors were not rebuilt.\n"
            f"  vectors in the database were written by : {stored}\n"
            f"  the current configuration is            : {current}\n"
            f"  ({chunks} chunks affected)\n\n"
            "Vectors from two different models are not comparable, so search "
            "would return plausible-looking nonsense rather than fail. Either "
            "restore the previous EMBEDDING_* settings in .env, or rebuild:\n"
            "  .venv/bin/python -m scripts.ingest --reset\n"
            "  .venv/bin/python -m scripts.extract --reset"
        )


async def create_schema(engine) -> None:
    """Create tables if they don't exist, then verify the embedding model
    matches the stored vectors. Safe to call on every startup."""
    from app.db.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    note = await check_embeddings(engine)
    if note:
        print(f"[db] {note}")

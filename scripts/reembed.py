"""
Switch the embedding model and re-embed every chunk in place.

Unlike `scripts.rechunk` (same model, just new chunk boundaries), this changes
the vector *dimension*, so it also swaps the pgvector column type. It does NOT
rebuild the database or re-ingest from source — it re-embeds the chunk text that
is already stored.

    # 1. edit .env:
    #      EMBEDDING_MODEL=intfloat/multilingual-e5-large
    #      EMBEDDING_DIM=1024
    #      EMBEDDING_PREFIXES=1
    # 2. stop the API server   (it holds the DB and caches the old model)
    # 3. run:
    python -m scripts.reembed
    # 4. restart the server;  python -m scripts.eval --collection samples

Takes a while — every chunk goes through the new model on CPU (~6k chunks ≈
20–40 min for e5-large). Ctrl-C is safe: it commits per batch and, on the next
run, finishes the chunks whose vector is still the old size. Any HNSW index is
dropped (rebuild it afterwards with `scripts.vector_index` if you use one).
"""

import argparse
import asyncio
import os

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.db.engine import resolve_database_url
from app.db.models import Chunk


async def main(batch: int) -> None:
    dim = int(os.environ.get("EMBEDDING_DIM", "384"))
    print(f"model  : {settings.embedding_model}")
    print(f"dim    : {dim}")
    engine = create_async_engine(resolve_database_url())

    async with engine.begin() as conn:
        cur = await conn.scalar(text(
            "SELECT atttypmod FROM pg_attribute "
            "WHERE attrelid = 'chunks'::regclass AND attname = 'embedding'"
        ))
        if cur != dim:
            print(f"resizing chunks.embedding -> vector({dim}) (was vector({cur}))")
            await conn.execute(text("DROP INDEX IF EXISTS ix_chunks_embedding_hnsw"))
            await conn.execute(text("ALTER TABLE chunks DROP COLUMN embedding"))
            await conn.execute(text(f"ALTER TABLE chunks ADD COLUMN embedding vector({dim})"))

    # imported here so it binds to the .env model
    from app.rag.embeddings import embed_passages

    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        total = await session.scalar(select(func.count()).select_from(Chunk))
        todo = await session.scalar(
            select(func.count()).select_from(Chunk).where(Chunk.embedding.is_(None))
        )
        print(f"{todo} of {total} chunks to embed")

        done = 0
        while True:
            rows = (
                await session.execute(
                    select(Chunk.id, Chunk.text).where(Chunk.embedding.is_(None)).limit(batch)
                )
            ).all()
            if not rows:
                break
            vectors = await asyncio.to_thread(embed_passages, [r.text for r in rows])
            for (cid, _), vec in zip(rows, vectors):
                await session.execute(
                    text("UPDATE chunks SET embedding = :v WHERE id = :i").bindparams(
                        v=str(list(vec)), i=cid
                    )
                )
            await session.commit()
            done += len(rows)
            print(f"  {done}/{todo}", flush=True)

    await engine.dispose()
    print("done — restart the server so it loads the new model")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=64)
    args = ap.parse_args()
    asyncio.run(main(args.batch))

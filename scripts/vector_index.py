"""
Add an HNSW approximate-nearest-neighbour index to chunks.embedding.

Without this, every vector search is an exact sequential scan over all chunks
(fine at a few thousand, slow past ~50k). HNSW makes it a real vector database:
sub-linear lookups at a small, tunable recall cost.

    python -m scripts.vector_index                 # build for the current EMBEDDING_DIM
    python -m scripts.vector_index --lists cosine  # (op class is cosine by default)
    python -m scripts.vector_index --drop          # remove it

Build time grows with row count and `m` / `ef_construction`; for ~10k chunks it
is seconds. The retriever already orders by `embedding <=> query` (cosine
distance), which this index accelerates with no code change.
"""

import argparse
import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.engine import resolve_database_url

INDEX = "ix_chunks_embedding_hnsw"


async def main(drop: bool, m: int, ef_construction: int) -> None:
    engine = create_async_engine(resolve_database_url())
    async with engine.begin() as conn:
        if drop:
            await conn.execute(text(f"DROP INDEX IF EXISTS {INDEX}"))
            print(f"dropped {INDEX}")
        else:
            # vector_cosine_ops matches the retriever's cosine_distance ordering.
            await conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS {INDEX} ON chunks "
                f"USING hnsw (embedding vector_cosine_ops) "
                f"WITH (m = {m}, ef_construction = {ef_construction})"
            ))
            n = await conn.scalar(text("SELECT count(*) FROM chunks"))
            print(f"built {INDEX} (m={m}, ef_construction={ef_construction}) over {n} chunks")
            print("query-time recall knob:  SET hnsw.ef_search = 40;  (default 40, higher = better recall, slower)")
    await engine.dispose()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--drop", action="store_true")
    ap.add_argument("--m", type=int, default=16, help="graph degree (16 is pgvector's default)")
    ap.add_argument("--ef-construction", type=int, default=64)
    args = ap.parse_args()
    asyncio.run(main(args.drop, args.m, args.ef_construction))

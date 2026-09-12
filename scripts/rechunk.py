"""
Re-chunk and re-embed every document already in the archive, in place.

Run this after changing `chunk_text()` or the text normalization. It reads each
document's stored `raw_text`, drops its old chunks, and writes new ones — no
re-ingest from source files, no database rebuild. The embedding *model* is
unchanged (same vector dimension), so this is safe and reversible by running it
again.

    python -m scripts.rechunk                 # all documents
    python -m scripts.rechunk --source data/farsi-courts   # only sources under a prefix
    python -m scripts.rechunk --batch 40

For an embedding-model change (different dimension) use
`scripts.upgrade_embeddings` instead — that one does need a rebuild.
"""

import argparse
import asyncio

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.engine import create_schema, resolve_database_url
from app.db.models import Chunk, Document
from app.rag.embeddings import embed_texts
from app.rag.ingest import chunk_text


async def main(source_prefix: str | None, batch: int) -> None:
    engine = create_async_engine(resolve_database_url())
    await create_schema(engine)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as session:
        q = select(Document.id, Document.source, Document.raw_text)
        if source_prefix:
            q = q.where(Document.source.like(f"{source_prefix}%"))
        rows = (await session.execute(q)).all()
        print(f"{len(rows)} documents to re-chunk", flush=True)

        before = await session.scalar(select(func.count()).select_from(Chunk))
        done = new_chunks = 0

        for start in range(0, len(rows), batch):
            group = rows[start : start + batch]
            plans = []
            pieces: list[str] = []
            for doc_id, source, raw in group:
                ch = chunk_text(raw or "")
                if not ch:
                    continue
                plans.append((doc_id, ch))
                pieces.extend(ch)

            vectors = await asyncio.to_thread(embed_texts, pieces) if pieces else []

            offset = 0
            for doc_id, ch in plans:
                await session.execute(delete(Chunk).where(Chunk.document_id == doc_id))
                n = len(ch)
                session.add_all([
                    Chunk(document_id=doc_id, text=piece, embedding=vec, chunk_index=i)
                    for i, (piece, vec) in enumerate(zip(ch, vectors[offset : offset + n]))
                ])
                offset += n
                new_chunks += n
            await session.commit()
            done += len(group)
            print(f"  {done}/{len(rows)} docs   ({new_chunks} chunks so far)", flush=True)

        after = await session.scalar(select(func.count()).select_from(Chunk))
        print(f"done — chunks {before} -> {after}")

    await engine.dispose()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", help="only documents whose source starts with this")
    ap.add_argument("--batch", type=int, default=40)
    args = ap.parse_args()
    asyncio.run(main(args.source, args.batch))

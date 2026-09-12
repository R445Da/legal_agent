"""
Ingest a directory of text files into the RAG index.

Usage:
    python -m scripts.ingest                # ingest data/cases/*.txt
    python -m scripts.ingest --reset        # wipe documents/chunks first
    python -m scripts.ingest path/to/dir    # ingest .txt files from another dir

Chunking / storage logic lives in app/rag/ingest.py so the API's /ingest
endpoint behaves identically. Replace `chunk_text` there when you plug in
real source data.
"""

import argparse
import asyncio
import pathlib
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.engine import create_schema, resolve_database_url
from app.db.models import Chunk, Document
from app.rag.embeddings import embed_texts
from app.rag.ingest import chunk_text, reset_all

DEFAULT_DIR = pathlib.Path("data/cases")


async def main(source_dir: pathlib.Path, reset: bool, batch_size: int) -> None:
    engine = create_async_engine(resolve_database_url())
    await create_schema(engine)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    files = sorted(source_dir.glob("*.txt"))
    if not files:
        sys.exit(f"No .txt files found in {source_dir}")

    async with Session() as session:
        if reset:
            await reset_all(session)
            await session.commit()
            print("Reset: cleared documents and chunks")

        existing_sources = set((await session.scalars(select(Document.source))).all())
        pending = [path for path in files if str(path) not in existing_sources]
        print(f"{len(pending):,} new files; {len(files) - len(pending):,} already indexed", flush=True)

        for start in range(0, len(pending), batch_size):
            batch = pending[start : start + batch_size]
            prepared: list[tuple[pathlib.Path, str, str, list[str]]] = []
            pieces: list[str] = []
            for path in batch:
                raw = path.read_text(encoding="utf-8")
                chunks = chunk_text(raw)
                if not chunks:
                    continue
                title = raw.splitlines()[0].strip() if raw.strip() else path.stem
                prepared.append((path, raw, title, chunks))
                pieces.extend(chunks)

            vectors = await asyncio.to_thread(embed_texts, pieces) if pieces else []
            offset = 0
            documents: list[Document] = []
            for path, raw, title, chunks in prepared:
                count = len(chunks)
                doc = Document(source=str(path), title=title, raw_text=raw, doc_metadata={})
                doc.chunks = [
                    Chunk(text=chunk, embedding=vector, chunk_index=index)
                    for index, (chunk, vector) in enumerate(
                        zip(chunks, vectors[offset : offset + count])
                    )
                ]
                offset += count
                documents.append(doc)
            session.add_all(documents)
            await session.commit()
            print(
                f"ok    {start + len(batch):,}/{len(pending):,} new files "
                f"({len(pieces):,} chunks in this batch)",
                flush=True,
            )

    await engine.dispose()
    print("done")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("source_dir", nargs="?", default=str(DEFAULT_DIR))
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--batch-size", type=int, default=32)
    args = ap.parse_args()
    if args.batch_size < 1:
        ap.error("--batch-size must be positive")
    asyncio.run(main(pathlib.Path(args.source_dir), args.reset, args.batch_size))

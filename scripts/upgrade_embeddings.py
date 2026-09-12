"""
One-shot: switch the embedding model and rebuild everything that depends on it.

The pgvector column width is fixed at import time from EMBEDDING_DIM, and vectors
from one model are not comparable to another's, so an embedding change is not a
migration — it is a full rebuild of the embedded Postgres, a re-ingest, and a
re-extract.

    # 1. edit .env:
    #      EMBEDDING_MODEL=intfloat/multilingual-e5-large
    #      EMBEDDING_DIM=1024
    #      EMBEDDING_PREFIXES=1
    # 2. stop the API server (it holds the embedded Postgres)
    # 3. run:
    python -m scripts.upgrade_embeddings --corpus data/farsi

This DROPS ./.pgdata. Only the on-disk `data/` corpus and the structured
extraction (re-run via the LLM) are rebuilt — anything archived only through the
UI that isn't also in `data/` is not recoverable. Back up first if unsure.
"""

import argparse
import asyncio
import os
import pathlib
import shutil
import sys

from app.config import settings


async def _run() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="data/farsi", help="folder of .txt files to re-ingest")
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    args = ap.parse_args()

    pg = pathlib.Path(settings.pg_data_dir)
    print(f"embedding model : {settings.embedding_model}")
    print(f"embedding dim   : {os.environ.get('EMBEDDING_DIM', '384')}")
    print(f"prefixes        : {os.environ.get('EMBEDDING_PREFIXES', '1')}")
    print(f"will delete     : {pg.absolute()}")
    print(f"will re-ingest  : {args.corpus}")
    if not args.yes and input("proceed? [y/N] ").strip().lower() != "y":
        sys.exit("aborted")

    if pg.exists():
        shutil.rmtree(pg)
        print(f"removed {pg}")

    # Imported here so the pgvector column picks up the new EMBEDDING_DIM.
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.db.engine import create_schema, resolve_database_url
    from app.rag.ingest import ingest_document

    engine = create_async_engine(resolve_database_url())
    await create_schema(engine)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    files = sorted(pathlib.Path(args.corpus).glob("*.txt"))
    if not files:
        sys.exit(f"no .txt files in {args.corpus}")
    async with Session() as session:
        for path in files:
            raw = path.read_text(encoding="utf-8")
            doc, status = await ingest_document(
                session, text=raw, source=str(path),
                title=raw.splitlines()[0].strip() if raw.strip() else path.stem,
                replace=True,
            )
            await session.commit()
            print(f"  {status:9} {path.name} -> {len(doc.chunks) if doc else 0} chunks")
    await engine.dispose()

    print("\nembeddings rebuilt. now run:  python -m scripts.extract --reset")
    print("then restart the API server and re-run:  python -m scripts.eval")


if __name__ == "__main__":
    asyncio.run(_run())

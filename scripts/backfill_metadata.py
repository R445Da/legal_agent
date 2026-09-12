"""
Backfill rules-based metadata (case number, court, date, year, group, doc kind)
onto every document already in the archive.

New documents get this automatically at ingest. Run this once after adding the
metadata extractor, or again after editing `app/rag/metadata.py`.

    python -m scripts.backfill_metadata
    python -m scripts.backfill_metadata --overwrite   # replace existing values too
"""

import argparse
import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm.attributes import flag_modified

from app.db.engine import resolve_database_url
from app.db.models import Document
from app.rag.metadata import extract_metadata


async def main(overwrite: bool) -> None:
    engine = create_async_engine(resolve_database_url())
    Session = async_sessionmaker(engine, expire_on_commit=False)
    changed = 0
    async with Session() as session:
        docs = (await session.scalars(select(Document))).all()
        for d in docs:
            meta = dict(d.doc_metadata or {})
            found = extract_metadata(d.raw_text or "")
            for k, v in found.items():
                if overwrite or not meta.get(k):
                    if meta.get(k) != v:
                        meta[k] = v
            if meta != (d.doc_metadata or {}):
                d.doc_metadata = meta
                flag_modified(d, "doc_metadata")
                changed += 1
        await session.commit()
    await engine.dispose()
    print(f"updated metadata on {changed}/{len(docs)} documents")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()
    asyncio.run(main(args.overwrite))

"""
Add documents: chunk + embed + index them AND run structured extraction, in
one pass. This is `scripts.ingest` followed by `scripts.extract`, but only for
the files you're adding now — the same thing the "بایگانی سند جدید" screen does
for a single pasted document, done for a whole folder.

    python -m scripts.add data/inbox           # add every new .txt in data/inbox
    python -m scripts.add path/to/file.txt     # add a single file
    python -m scripts.add data/inbox --no-extract   # index only, skip the LLM step
    python -m scripts.add data/inbox --move-to data/archive   # move files after success

For each file that isn't already indexed:
  1. chunk -> embed -> store as a Document (+ Chunks)          [retrieval]
  2. LLM extract -> parties / representation / events / entities / tags
     -> store as an Entry, linked to related existing documents [structured]

Extraction uses the model in .env (LLM_PROVIDER / LLM_MODEL). On the local
model it is ~15-40 s per document, so adding a large folder takes a while;
Ctrl-C is safe — already-committed documents stay, and re-running picks up
where it left off.
"""

import argparse
import asyncio
import pathlib
import shutil
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.engine import create_schema, resolve_database_url
from app.db.models import Document, Entry
from app.llm.factory import get_llm_provider
from app.rag.ingest import ingest_document
from app.rag.orchestrator import extract_entry, find_related


def _files(target: pathlib.Path) -> list[pathlib.Path]:
    if target.is_file():
        return [target]
    if target.is_dir():
        return sorted(target.glob("*.txt"))
    sys.exit(f"not found: {target}")


async def _extract_one(session, llm, doc: Document) -> Entry:
    draft = await extract_entry(llm, doc.raw_text)
    related = await find_related(session, doc.raw_text, exclude_source=doc.source)
    entry = Entry(
        document_id=doc.id,
        kind=draft.get("kind", "session"),
        title=draft.get("title") or doc.title,
        summary=draft.get("summary", ""),
        parties=draft.get("parties", []),
        representation=draft.get("representation", []),
        events=draft.get("events", []),
        entities=draft.get("entities", {}),
        tags=draft.get("tags", []),
        related_ids=[r["document_id"] for r in related],
        raw_text=doc.raw_text,
    )
    session.add(entry)
    return entry


async def main(target: pathlib.Path, do_extract: bool, move_to: pathlib.Path | None) -> None:
    engine = create_async_engine(resolve_database_url())
    await create_schema(engine)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    llm = get_llm_provider() if do_extract else None
    if move_to:
        move_to.mkdir(parents=True, exist_ok=True)

    files = _files(target)
    if not files:
        sys.exit(f"no .txt files in {target}")

    async with Session() as session:
        indexed = set((await session.scalars(select(Document.source))).all())
        extracted = set(
            str(x) for x in (await session.scalars(select(Entry.document_id))).all()
        )

        added = skipped = 0
        for i, path in enumerate(files, 1):
            src = str(path)
            raw = path.read_text(encoding="utf-8")

            if src in indexed:
                # already indexed — just backfill an Entry if it's missing
                doc = await session.scalar(select(Document).where(Document.source == src))
                if do_extract and doc is not None and str(doc.id) not in extracted:
                    await _extract_one(session, llm, doc)
                    await session.commit()
                    print(f"[{i}/{len(files)}] extract-only  {path.name}", flush=True)
                else:
                    skipped += 1
                continue

            title = raw.splitlines()[0].strip() if raw.strip() else path.stem
            doc, status = await ingest_document(session, text=raw, source=src, title=title[:200])
            if doc is None:
                print(f"[{i}/{len(files)}] {status:8} {path.name}", flush=True)
                continue
            # Commit the index first: a slow or failing extraction must not lose
            # an already-embedded document. `scripts.extract` backfills the rest.
            await session.commit()
            note = f"{len(doc.chunks)} chunks"

            if do_extract:
                try:
                    entry = await _extract_one(session, llm, doc)
                    await session.commit()
                    reps = ", ".join(f"{r.get('lawyer')}→{r.get('client')}" for r in entry.representation)
                    note += f"; entry [{reps or 'no representation'}]"
                except Exception as exc:  # noqa: BLE001 — keep going; entry is backfillable
                    await session.rollback()
                    note += f"; EXTRACT FAILED ({type(exc).__name__}) — run scripts.extract later"
            added += 1
            print(f"[{i}/{len(files)}] added     {path.name}  ({note})", flush=True)

            if move_to and path.is_file():
                shutil.move(src, move_to / path.name)

    await engine.dispose()
    print(f"done — {added} added, {skipped} already present")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="index + extract new documents in one pass")
    ap.add_argument("target", help="a .txt file or a folder of .txt files")
    ap.add_argument("--no-extract", action="store_true", help="index only, skip the LLM extraction step")
    ap.add_argument("--move-to", metavar="DIR", help="move each file here after it is added (a simple inbox pattern)")
    args = ap.parse_args()
    asyncio.run(main(
        pathlib.Path(args.target),
        do_extract=not args.no_extract,
        move_to=pathlib.Path(args.move_to) if args.move_to else None,
    ))

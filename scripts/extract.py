"""
Backfill structured Entry rows for documents that don't have one yet.

    python -m scripts.extract              # every document missing an entry
    python -m scripts.extract --reset      # drop all entries first, redo

This is the "let the rest roll out — it finds the important stuff and fills
the table" step: run the LLM extractor over the whole archive so the
relational views (who represented whom, topics, entities) have data.
"""

import argparse
import asyncio

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.engine import create_schema, resolve_database_url
from app.db.models import Document, Entry
from app.llm.factory import get_llm_provider
from app.rag.orchestrator import extract_entry, find_related


async def main(reset: bool) -> None:
    engine = create_async_engine(resolve_database_url())
    await create_schema(engine)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    llm = get_llm_provider()

    async with Session() as session:
        if reset:
            await session.execute(delete(Entry))
            await session.commit()
            print("reset: cleared entries")

        have = set(
            (await session.execute(select(Entry.document_id))).scalars().all()
        )
        docs = (await session.execute(select(Document))).scalars().all()
        todo = [d for d in docs if d.id not in have]
        print(f"{len(todo)} documents to extract (of {len(docs)})")

        for doc in todo:
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
            await session.commit()
            reps = ", ".join(f"{r.get('lawyer')}→{r.get('client')}" for r in entry.representation)
            print(f"  ok  {doc.source}  [{reps or 'no representation found'}]")

    await engine.dispose()
    print("done")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true")
    args = ap.parse_args()
    asyncio.run(main(args.reset))

"""
Turn the relevance labels collected in the web app into a judged eval set.

Every time you thumbs-up / thumbs-down a retrieved chunk in the assistant or
search view, a `Label(kind="relevance", query=..., target_id=<chunk id>, value=1|0)`
is stored. This rolls those up per query into the same JSONL format
`scripts/eval.py` reads:

    {"q": "...", "expect": ["<source substring>", ...], "kind": "judged"}

    python -m scripts.export_eval                     # -> eval/judged.jsonl
    python -m scripts.export_eval eval/mine.jsonl     # custom path
    python -m scripts.export_eval --min-pos 2         # only queries with >=2 positives

Then:  python -m scripts.eval eval/judged.jsonl
"""

import argparse
import asyncio
import json
import pathlib
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.engine import resolve_database_url
from app.db.models import Chunk, Document, Label


def _key(source: str) -> str:
    """A stable substring eval.py can match on: the filename stem without ext."""
    stem = pathlib.Path(source).name
    return re.sub(r"\.(txt|md|json)$", "", stem)


async def main(out: pathlib.Path, min_pos: int) -> None:
    engine = create_async_engine(resolve_database_url())
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as session:
        labels = (
            await session.execute(
                select(Label).where(Label.kind == "relevance", Label.value == "1")
            )
        ).scalars().all()
        if not labels:
            print("no positive relevance labels yet — thumbs-up some results in the app first")
            return

        chunk_ids = {lb.target_id for lb in labels}
        rows = (
            await session.execute(
                select(Chunk.id, Document.source)
                .join(Document, Chunk.document_id == Document.id)
                .where(Chunk.id.in_([__import__("uuid").UUID(c) for c in chunk_ids]))
            )
        ).all()
        src_of = {str(cid): source for cid, source in rows}

        per_query: dict[str, set[str]] = {}
        for lb in labels:
            src = src_of.get(lb.target_id)
            if src and lb.query:
                per_query.setdefault(lb.query.strip(), set()).add(_key(src))

    out.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with out.open("w", encoding="utf-8") as f:
        for q, expect in sorted(per_query.items()):
            if len(expect) < min_pos:
                continue
            f.write(json.dumps(
                {"q": q, "expect": sorted(expect), "kind": "judged",
                 "want_all": len(expect) > 1},
                ensure_ascii=False,
            ) + "\n")
            n += 1
    await engine.dispose()
    print(f"wrote {n} judged queries -> {out}")
    print(f"run:  python -m scripts.eval {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?", default="eval/judged.jsonl")
    ap.add_argument("--min-pos", type=int, default=1)
    args = ap.parse_args()
    asyncio.run(main(pathlib.Path(args.out), args.min_pos))

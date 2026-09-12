"""
Retrieval eval harness (CLI). Same logic as the POST /eval endpoint.

    python -m scripts.eval                     # eval/farsi.jsonl, top_k=5
    python -m scripts.eval eval/farsi.jsonl -k 8
    python -m scripts.eval --ask               # also run the full pipeline per query

Reports hit@1 / hit@3 / hit@k / MRR and, for multi-doc questions, cov@k.
Swap EMBEDDING_MODEL / LLM_MODEL in .env, re-run, compare.
"""

import argparse
import asyncio
import pathlib
import sys

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.db.engine import create_schema, resolve_database_url
from app.llm.factory import get_llm_provider
from app.rag.evaluate import load_cases, run_eval


async def main(path: pathlib.Path, top_k: int, do_ask: bool, collection: str | None) -> None:
    if not path.exists():
        sys.exit(f"no eval file at {path}")
    cases = load_cases(path)

    engine = create_async_engine(resolve_database_url())
    await create_schema(engine)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    llm = get_llm_provider() if do_ask else None

    print(f"eval: {path}   embed={settings.embedding_model}   k={top_k}"
          + (f"   collection={collection}" if collection else "")
          + (f"   llm={getattr(llm, 'model', '?')}" if llm else ""))
    print("-" * 72)

    async with Session() as session:
        result = await run_eval(session, cases, top_k=top_k, llm=llm, collection=collection)

    for row in result["cases"]:
        mark = f"@{row['rank']}" if row["rank"] else "MISS"
        line = f"[{mark:>5}] {row['q'][:58]}"
        if "coverage" in row:
            line += f"   cov={row['coverage']:.0%}"
        print(line)
        if "answer" in row:
            print(f"         ↳ {row['answer'].strip()[:200].replace(chr(10), ' ')}")

    print("-" * 72)
    print("   ".join(f"{k} {v}" for k, v in result["metrics"].items()))
    await engine.dispose()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default="eval/farsi.jsonl")
    ap.add_argument("-k", "--top-k", type=int, default=5)
    ap.add_argument("--ask", action="store_true", help="also run the full RAG pipeline per query")
    ap.add_argument("--collection", help="scope retrieval to one bucket: samples | rulings | cases-en | uploads")
    args = ap.parse_args()
    asyncio.run(main(pathlib.Path(args.path), args.top_k, args.ask, args.collection))

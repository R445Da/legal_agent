"""
Run every demo stage end to end on the current model and check expectations.

    python -m scripts.demo_stages                 # model from .env
    python -m scripts.demo_stages --model groq::openai/gpt-oss-20b
    python -m scripts.demo_stages --stage law_lookup --stage conversational_filing

Prints one line per prompt (intent, grounding status, problems) and exits 1
when any expectation failed — the demo script doubling as an acceptance test.
"""

import argparse
import asyncio
import sys

from dotenv import load_dotenv

load_dotenv()

from app.demo.stages import BY_ID, STAGES, run_stage  # noqa: E402


async def main(args) -> int:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.db.engine import create_schema, resolve_database_url
    from app.llm import registry

    llm = registry.resolve(args.model) if args.model else registry.resolve(registry.default_id())
    engine = create_async_engine(resolve_database_url())
    await create_schema(engine)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    stages = [BY_ID[s] for s in args.stage] if args.stage else STAGES
    failed = 0
    async with sessions() as session:
        for stage in stages:
            print(f"== {stage.id} — {stage.title}")
            if not stage.prompts:
                print("   (no prompts: shown in the UI only)")
                continue
            for report in await run_stage(session, llm, stage):
                mark = "FAIL" if report["problems"] else "ok  "
                failed += bool(report["problems"])
                print(f"   {mark} {report['prompt']:<60} {report.get('intent') or report.get('status') or ''}"
                      f"  {report.get('grounding') or ''}  {'; '.join(report['problems'])}")
    await engine.dispose()
    print(f"-- {len(stages)} stages, {failed} failed prompts --")
    return 1 if failed else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None, help="registry id, e.g. groq::openai/gpt-oss-20b")
    ap.add_argument("--stage", action="append", help="stage id (repeatable)")
    sys.exit(asyncio.run(main(ap.parse_args())))

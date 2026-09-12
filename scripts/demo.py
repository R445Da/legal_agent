"""
Run one document through the entry-building pipeline, on the terminal.

This is the same engine the chat uses (`app/rag/workflow.py`) — same steps, same
gates, same Run/RunStep rows — just driven from a script so you can demo it, time
it, or compare models without clicking.

    python -m scripts.demo                              # sample doc, review mode
    python -m scripts.demo --mode auto                  # no gates, straight to commit
    python -m scripts.demo --model local::qwen2.5:7b    # compare a local model
    python -m scripts.demo --file mydoc.txt             # your own text
    python -m scripts.demo --keep                       # don't delete the entry after

Gates are auto-approved here (that's the point of a script). Use the UI to
actually edit at each gate.
"""

import argparse
import asyncio
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)

from sqlalchemy import delete, select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.db.engine import create_schema, resolve_database_url  # noqa: E402
from app.db.models import Document, Entry, Label, Run  # noqa: E402
from app.llm import registry  # noqa: E402
from app.rag import workflow  # noqa: E402

SAMPLE = Path(__file__).resolve().parent.parent / "samples" / "laheye-defaeiye.txt"
DIM, OFF, B, G, R, Y = "\033[2m", "\033[0m", "\033[1m", "\033[32m", "\033[31m", "\033[33m"


def _icon(status: str) -> str:
    return {"done": f"{G}✓{OFF}", "failed": f"{R}✗{OFF}",
            "awaiting_input": f"{Y}✋{OFF}"}.get(status, "·")


def _show(view: dict) -> None:
    for s in view["steps"]:
        ms = f"{s['ms']:>6}ms" if s.get("ms") else " " * 8
        print(f"  {_icon(s['status'])} {s['step_id']:<9} {DIM}{ms}{OFF}  {s.get('detail') or ''}")
        if s.get("error"):
            print(f"      {R}{s['error'][:150]}{OFF}")


def _approve(step: dict) -> dict:
    """What the UI's gate buttons send back. A script accepts the proposal."""
    p, sid = step.get("payload") or {}, step["step_id"]
    if sid == "labels" and p.get("mode") == "review":     # the one review gate
        return {k: p[k] for k in ("draft", "timeline", "similar", "labels") if k in p}
    return {"extract": lambda: {"draft": p},
            "timeline": lambda: {"timeline": p.get("rows", [])},
            "similar": lambda: {"similar": p.get("items", [])},
            "labels": lambda: {"labels": p.get("labels", [])}}.get(sid, dict)()


async def main(args) -> int:
    text = Path(args.file).read_text() if args.file else SAMPLE.read_text()
    engine = create_async_engine(resolve_database_url())
    await create_schema(engine)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    llm = registry.resolve(args.model) if args.model else registry.resolve(registry.default_id())
    model_id = args.model or registry.default_id()
    print(f"\n{B}model{OFF} {model_id}   {B}mode{OFF} {args.mode}   "
          f"{B}input{OFF} {len(text)} chars\n")

    t0 = time.perf_counter()
    async with Session() as s:
        view = await workflow.start(s, raw_text=text, source=f"demo/{int(t0)}",
                                    llm=llm, mode=args.mode, forced_intent="archive")
    _show(view)

    gates = 0
    while view["status"] not in ("committed", "failed", "abandoned"):
        gate = next((x for x in view["steps"] if x["status"] == "awaiting_input"), None)
        if gate is None:
            print(f"  {R}stalled at status={view['status']}{OFF}")
            break
        gates += 1
        print(f"  {DIM}→ auto-approving gate «{gate['label']}»{OFF}")
        async with Session() as s:
            view = await workflow.advance(s, view["id"], llm, user_patch=_approve(gate))
        _show(view)

    total = time.perf_counter() - t0
    colour = G if view["status"] == "committed" else R
    print(f"\n  {colour}{view['status']}{OFF}  ·  {gates} gate(s)  ·  {B}{total:.1f}s{OFF}")

    if view.get("entry_id"):
        async with Session() as s:
            e = await s.get(Entry, view["entry_id"])
            if e:
                ent = e.entities or {}
                print(f"\n{B}── the record it built ──{OFF}")
                print(f"  عنوان     {e.title}")
                print(f"  شماره     {ent.get('case_number') or '—'}")
                print(f"  دادگاه    {ent.get('court') or '—'}")
                print(f"  طرفین     " + "، ".join(
                    f"{p.get('role')}: {p.get('name')}" for p in (e.parties or [])
                    if isinstance(p, dict)) or "—")
                for ev in (e.events or []):
                    print(f"  رویداد    {ev.get('date','')} — {str(ev.get('description',''))[:60]}")
                print(f"  برچسب‌ها   " + "، ".join(e.tags or []) or "—")
                print(f"  مشابه‌ها   {len(e.related or [])} مورد")

    print(f"\n  {DIM}console: http://localhost:8000/runs/view?token=$API_TOKEN{OFF}")

    if not args.keep:
        async with Session() as s:
            for e in (await s.execute(
                select(Entry).where(Entry.raw_text == text))).scalars():
                await s.execute(delete(Label).where(Label.target_id == str(e.id)))
                if e.document_id:
                    d = await s.get(Document, e.document_id)
                    if d:
                        await s.delete(d)
                await s.delete(e)
            for r in (await s.execute(
                select(Run).where(Run.raw_text == text))).scalars():
                await s.delete(r)
            await s.commit()
        print(f"  {DIM}(demo data removed — pass --keep to keep it){OFF}\n")
    else:
        print()

    await engine.dispose()
    return 0 if view["status"] == "committed" else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", default="review", choices=list(workflow.RUN_MODES))
    ap.add_argument("--model", help="registry id, e.g. groq::openai/gpt-oss-20b")
    ap.add_argument("--file", help="a text file to ingest instead of the sample")
    ap.add_argument("--keep", action="store_true", help="keep the entry afterwards")
    sys.exit(asyncio.run(main(ap.parse_args())))

"""
Write the archive into the Obsidian vault as markdown notes.

    python -m scripts.export_vault                 # backfill everything
    python -m scripts.export_vault --watch         # and keep it in sync
    python -m scripts.export_vault --vault ~/path  # a vault somewhere else
    python -m scripts.export_vault --cypher out.cypher

The notes land in `<vault>/آرشیو/` and nowhere else — see `app/rag/vaultsync.py`
for why that boundary matters. Once they exist, Obsidian's own graph view shows
the archive, and section ۲۰ of the app draws the same files.

`--watch` polls row counts and rewrites only the notes whose content changed,
so an open note in Obsidian does not flicker on every pass.
"""

import argparse
import asyncio
import time

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.engine import resolve_database_url
from app.rag import graph, vaultsync


async def _export(Session) -> tuple[dict, tuple]:
    async with Session() as session:
        result = await vaultsync.export_all(session)
        mark = await vaultsync.fingerprint(session)
    return result, mark


async def _cypher(Session, out_path: str) -> int:
    """The same pass, as Cypher — the vault and a graph database from one run."""
    async with Session() as session:
        whole = await graph.whole(session, types=("case", "law", "person", "org"))
        text = graph.to_cypher(whole)
    with open(out_path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return len(text.splitlines())


async def main() -> int:
    ap = argparse.ArgumentParser(description="Export the archive as Obsidian notes")
    ap.add_argument("--vault", help="vault folder (default: graphify-out/obsidian, or $VAULT_DIR)")
    ap.add_argument("--watch", action="store_true", help="rebuild whenever the data changes")
    ap.add_argument("--interval", type=int, default=15, help="seconds between polls when watching")
    ap.add_argument("--cypher", help="also write the graph as Cypher to this path")
    args = ap.parse_args()

    if args.vault:
        vaultsync.VAULT_DIR = args.vault

    engine = create_async_engine(resolve_database_url(), echo=False)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    try:
        result, mark = await _export(Session)
        print(f"{result['notes']} یادداشت · {result['written']} نوشته شد → {result['vault']}/آرشیو")

        if args.cypher:
            lines = await _cypher(Session, args.cypher)
            print(f"{lines} خط Cypher → {args.cypher}")

        if not args.watch:
            return 0

        print(f"در حال پایش… (هر {args.interval} ثانیه، Ctrl-C برای توقف)")
        while True:
            await asyncio.sleep(args.interval)
            async with Session() as session:
                now = await vaultsync.fingerprint(session)
            if now == mark:
                continue
            result, mark = await _export(Session)
            print(f"[{time.strftime('%H:%M:%S')}] {result['written']} یادداشت به‌روز شد")
    except KeyboardInterrupt:
        return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

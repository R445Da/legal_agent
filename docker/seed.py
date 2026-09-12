"""
First-run database seeding.

The image ships a pg_dump custom-format archive at docker/seed.dump (the 806
ingested court rulings: documents, chunks with vectors, and extracted entries).
This script starts the embedded PostgreSQL against PG_DATA_DIR and, if the
`documents` table isn't there yet, restores the dump into it. On every later
start it finds the table populated and does nothing.

Run by docker/entrypoint.sh before uvicorn.
"""

import os
import pathlib
import subprocess
import sys

import pgserver
from pgserver._commands import POSTGRES_BIN_PATH

DATA_DIR = pathlib.Path(os.environ.get("PG_DATA_DIR", "/data/pgdata")).absolute()
DUMP = pathlib.Path(__file__).with_name("seed.dump")


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    server = pgserver.get_server(DATA_DIR)  # inits the cluster + starts postgres

    exists = "t" in server.psql(
        "SELECT to_regclass('public.documents') IS NOT NULL;"
    ).split()

    if exists:
        rows = " ".join(server.psql("SELECT count(*) FROM documents;").split())
        print(f"[seed] database already populated ({rows} in documents) — skipping restore")
        return

    if not DUMP.is_file():
        print(f"[seed] no dump at {DUMP}; starting with an empty database", file=sys.stderr)
        return

    print(f"[seed] empty database — restoring {DUMP} ({DUMP.stat().st_size // 1024} KiB)")
    subprocess.run(
        [
            str(POSTGRES_BIN_PATH / "pg_restore"),
            "--no-owner",
            "--no-privileges",
            "--dbname",
            server.get_uri(),
            str(DUMP),
        ],
        check=True,
    )
    rows = " ".join(server.psql("SELECT count(*) FROM documents;").split())
    print(f"[seed] restore complete ({rows} in documents)")


if __name__ == "__main__":
    main()

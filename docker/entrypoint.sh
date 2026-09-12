#!/bin/sh
# First-run setup, then hand off to the CMD (Streamlit).
#
#   1. seed.py       — restore the bundled Postgres dump into an empty volume;
#                      no-op once the volume is populated
#   2. migrate_fts   — add the lexical (tsvector) columns to chunks + entries;
#                      idempotent, needed because the seed dump predates them
set -e

python /app/docker/seed.py
python -m scripts.migrate_fts

exec "$@"

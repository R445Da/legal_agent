#!/usr/bin/env bash
# Runs once when the Codespace is created (devcontainer.json postCreateCommand).
# Every step is idempotent, so re-running it on an existing Codespace is safe.
#
# Order matters:
#   1. PostgreSQL 16 client. docker/seed.dump is a pg_dump *custom* archive
#      (format 1.15, written by PG 16): `psql <` cannot read it at all, and
#      Debian's stock postgresql-client (15) refuses the format, so the client
#      comes from the PostgreSQL apt repository.
#   2. venv
#   3. .env — the offline mock model unless ANTHROPIC_API_KEY is a Codespaces
#      secret. Groq is out: a Codespace runs on Azure, a datacenter IP.
#   4. Restore the 806-ruling archive into the EMPTY pgvector database.
#      With the schema created first, pg_restore errors on every table that
#      already exists and exits 1, which `set -e` turns into a half-built
#      Codespace. (The previous script also fed the archive to `psql <`,
#      which cannot read the custom format, and silenced the failure.)
#   5. create_schema (enables pgvector, adds the tables the dump predates,
#      applies the insurance-edition column upgrades) + the two migrations.
#   6. Pre-download the retrieval models, so the first query is not a
#      ten-minute hang, then seed the insurance edition if it is missing.
set -eu
cd /workspace

DB_URL="${DATABASE_URL:-postgresql://postgres:postgres@db:5432/postgres}"
say() { printf '\n\033[36m· %s\033[0m\n' "$*"; }

say "PostgreSQL 16 client"
if ! pg_restore --version 2>/dev/null | grep -qE ' (1[6-9]|[2-9][0-9])\.'; then
  sudo install -d /usr/share/postgresql-common/pgdg
  sudo curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
       https://www.postgresql.org/media/keys/ACCC4CF8.asc
  . /etc/os-release
  echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt ${VERSION_CODENAME}-pgdg main" \
    | sudo tee /etc/apt/sources.list.d/pgdg.list >/dev/null
  sudo apt-get update -qq
  sudo apt-get install -y -qq --no-install-recommends postgresql-client-16
fi
pg_restore --version

say "python environment"
[ -x .venv/bin/python ] || python -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r docker/requirements-cloud.txt

say ".env"
if [ ! -f .env ]; then
  if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
    PROVIDER=anthropic; MODEL=claude-haiku-4-5; ROUTER=anthropic::claude-haiku-4-5
  else
    PROVIDER=mock; MODEL=rules-v1; ROUTER=mock::rules-v1
  fi
  cat > .env <<ENV
# Written by .devcontainer/setup.sh.
#
# A Codespace runs on Azure — a datacenter IP — and Groq's edge blocks those.
# The choices are Anthropic (add ANTHROPIC_API_KEY as a Codespaces secret at
# github.com/settings/codespaces, delete this file, re-run the script) or the
# offline rule-based mock, which walks every screen and the whole pipeline
# with no key and no spend.
LLM_PROVIDER=${PROVIDER}
LLM_MODEL=${MODEL}
ROUTER_MODEL=${ROUTER}

# DATABASE_URL comes from devcontainer.json (remoteEnv), not from here.

# Must match the vectors in docker/seed.dump — app/db/engine.py refuses to
# start on a mismatch.
EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
EMBEDDING_DIM=384
EMBEDDING_PREFIXES=0
HYBRID=1
RERANK=1
RERANK_MODEL=jinaai/jina-reranker-v2-base-multilingual
RETRIEVE_CANDIDATES=30
RERANK_TOP=8
TS_CONFIG=simple
STT=0
API_TOKEN=devtoken
ENV
  echo "  provider: ${PROVIDER} ${MODEL}"
fi
set -a; . ./.env; set +a
export DATABASE_URL="$DB_URL"

say "waiting for postgres"
until pg_isready -q -d "$DB_URL"; do sleep 1; done

has_docs() { [ "$(psql "$DB_URL" -tAc "select to_regclass('public.documents') is not null")" = "t" ]; }
if [ -f docker/seed.dump ] && ! has_docs; then
  say "restoring docker/seed.dump (806 rulings)"
  psql -q "$DB_URL" -c "CREATE EXTENSION IF NOT EXISTS vector"
  pg_restore --no-owner --no-privileges --dbname "$DB_URL" docker/seed.dump
  echo "  $(psql "$DB_URL" -tAc 'select count(*) from documents') documents"
fi

say "schema + migrations"
.venv/bin/python -c "
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from app.db.engine import create_schema, resolve_database_url
async def main():
    e = create_async_engine(resolve_database_url()); await create_schema(e); await e.dispose()
asyncio.run(main())"
.venv/bin/python -m scripts.migrate_fts
.venv/bin/python -m scripts.migrate_runs

say "retrieval models (one-time download, kept in the fastembed volume)"
.venv/bin/python -c "
from app.rag import embeddings, rerank
embeddings._model(); print('  embedder ready')
if rerank.enabled(): rerank._model(); print('  reranker ready')"

if [ "$(psql "$DB_URL" -tAc 'select count(*) from legal_cases')" = "0" ]; then
  say "insurance edition: statute base + 120 mock cases"
  .venv/bin/python -m scripts.seed_mock --n 120
fi

cat <<'DONE'

  Ready.

    .venv/bin/streamlit run streamlit_app.py --server.port 8501
    .venv/bin/uvicorn app.main:app --port 8000        # JSON API, optional
    API_TOKEN=devtoken scripts/check.sh               # smoke-test the API

  Port 8501 forwards automatically — VS Code opens a preview, and the Ports
  tab has a public URL you can share.
DONE

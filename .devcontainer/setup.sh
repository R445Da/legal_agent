#!/usr/bin/env bash
# Runs once when the Codespace is created.
set -eu
cd /workspace

echo "· python environment"
python -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r docker/requirements-cloud.txt

echo "· .env (Codespace defaults — a datacenter IP, so NOT Groq)"
if [ ! -f .env ]; then
  cat > .env <<'ENV'
# A Codespace runs on Azure, i.e. a datacenter IP — Groq's edge blocks those.
# Use Anthropic (works from datacenters) or point LOCAL_LLM_URL at an Ollama.
LLM_PROVIDER=anthropic
LLM_MODEL=claude-opus-5
ROUTER_MODEL=anthropic::claude-haiku-4-5
# Set ANTHROPIC_API_KEY as a Codespaces secret, not here.

DATABASE_URL=postgresql://postgres:postgres@db:5432/postgres

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
fi

echo "· schema"
.venv/bin/python -c "
import asyncio
from dotenv import load_dotenv; load_dotenv('.env', override=True)
from sqlalchemy.ext.asyncio import create_async_engine
from app.db.engine import create_schema, resolve_database_url
async def main():
    e = create_async_engine(resolve_database_url()); await create_schema(e); await e.dispose()
asyncio.run(main())"

if [ -f docker/seed.dump ]; then
  echo "· seeding the archive"
  PGPASSWORD=postgres psql -h db -U postgres -d postgres -q < docker/seed.dump 2>/dev/null || true
fi

cat <<'DONE'

  Ready.

    .venv/bin/streamlit run streamlit_app.py --server.port 8501

  The port forwards automatically — VS Code opens a preview, and the
  Ports tab has a public URL you can share.

  Set ANTHROPIC_API_KEY first:
    github.com/settings/codespaces  →  New secret
DONE

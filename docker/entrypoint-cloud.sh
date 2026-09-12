#!/usr/bin/env bash
# Cloud entrypoint: verify the managed database, then serve.
set -eu

PORT="${PORT:-${STREAMLIT_SERVER_PORT:-8501}}"

if [ "${DATABASE_URL:-embedded}" = "embedded" ]; then
  echo "FATAL: DATABASE_URL is unset (or 'embedded')."
  echo "  This image has no bundled Postgres. Point it at a managed one:"
  echo "    DATABASE_URL=postgresql://user:pass@host:5432/postgres"
  echo "  Supabase and Neon both ship pgvector on their free tier."
  exit 1
fi

echo "· database  $(printf '%s' "$DATABASE_URL" | sed -E 's#//[^@]*@#//***@#')"
echo "· provider  ${LLM_PROVIDER:-<unset>} ${LLM_MODEL:-}"
[ -z "${LLM_PROVIDER:-}" ] && echo "  ! LLM_PROVIDER is unset — the app will start but cannot answer."

# create_schema() also runs the embedding-fingerprint guard, so a mismatch
# between this image's EMBEDDING_MODEL and the stored vectors fails here,
# loudly, rather than silently returning wrong search results later.
python - <<'PY'
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from app.db.engine import create_schema, resolve_database_url

async def main():
    engine = create_async_engine(resolve_database_url())
    await create_schema(engine)
    await engine.dispose()
    print("· schema ready")

asyncio.run(main())
PY

exec streamlit run streamlit_app.py --server.port "$PORT"

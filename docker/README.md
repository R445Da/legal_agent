# Running in Docker

One image, one container. The chat model is Groq over HTTPS; everything else —
the Streamlit app, PostgreSQL + pgvector, the retrieval models, and a seed
database of 806 court rulings — is inside the image.

## What you actually get

- **Not a VM.** On Linux (you're on Debian) a container is just isolated host
  processes sharing your kernel — no guest OS, no virtual disk. `docker stats`
  shows it sitting next to your other processes. (On macOS/Windows Docker Desktop
  runs one small Linux VM for *all* containers; still not one-VM-per-image.)
- **~2.3 GB image.** Most of it is the jina reranker (~1.1 GB) and the MiniLM
  embedder, baked in so retrieval needs no network.
- **A named volume** `legal-rag_pgdata` holding the Postgres data directory. The
  container is disposable; the volume is your data.

## First run

```bash
cd legal-rag-ui-workbench
cp .env.docker.example .env.docker      # then put your GROQ_API_KEY in it
docker compose up --build
```

In order, first time only:

1. **build** — base image, pip install, bake the ONNX models. ~5–15 min, once.
2. **entrypoint** — restore `docker/seed.dump` into the fresh volume (806 docs,
   ~16 entries), then `migrate_fts` adds the tsvector columns.
3. **streamlit** — starts on `:8501`. First page load compiles the embedder;
   give it ~30 s.

Open **http://localhost:8501**.

## Every run after that

```bash
docker compose up          # seconds — volume is populated, models are baked
docker compose down         # stop, keep the data
docker compose down -v      # stop and wipe the pgdata volume (re-seeds next up)
```

## Poking around inside

```bash
docker compose ps                         # is it healthy?
docker compose logs -f app                # live logs
docker compose exec app sh                # a shell in the container
docker compose exec app python -m scripts.eval        # retrieval metrics
docker compose exec app psql "$(...)"     # see 'psql' below
```

`psql` into the embedded database:

```bash
docker compose exec app python - <<'PY'
import pgserver, os
print(pgserver.get_server(os.environ["PG_DATA_DIR"]).get_uri())
PY
# then: docker compose exec app /opt/venv/.../pg_restore ... (or just use the app)
```

## Tuning without rebuilding

Edit `.env.docker`, then `docker compose up -d`. Useful knobs:

| var | default | effect |
|---|---|---|
| `LLM_MODEL` | `openai/gpt-oss-20b` | `openai/gpt-oss-120b` = better Persian, slower |
| `RERANK_TOP` | `8` | lower = faster retrieval; `RERANK=0` = fastest, less precise |
| `ROUTER_MODEL` | `groq::openai/gpt-oss-20b` | the classifier model — keep it fast |
| `API_TOKEN` | unset | set to require `Authorization: Bearer` (FastAPI API only) |

**Do not change** `EMBEDDING_MODEL` / `EMBEDDING_DIM` / `TS_CONFIG` — the seed
vectors and the tsvector index were built with these.

## Running the JSON API too

The Streamlit app doesn't need it, but scripts and the ngrok tunnel do:

```bash
docker compose exec app uvicorn app.main:app --host 0.0.0.0 --port 8000
# add  - "8000:8000"  to the compose ports first
```

## GPU / offline / bigger corpus

- **GPU** does nothing here — the LLM is remote (Groq) and the CPU models are
  small. Latency is dominated by the reranker; lower `RERANK_TOP` instead.
- **Fully offline** is now a compose profile rather than a rewrite. `ollama` is
  a service in `docker-compose.yml`, off unless you ask for it:

  ```bash
  docker compose --profile pull up ollama-pull   # pre-pull qwen2.5:3b
  docker compose --profile local up              # app + ollama
  ```

  Then uncomment the `LLM_PROVIDER=local` block in `.env.docker`. Compose already
  sets `LOCAL_LLM_URL=http://ollama:11434` — the sibling service, not localhost.
  A GPU is worth reserving in this mode (commented `deploy:` block); on the Groq
  path it does nothing.
- **More than 806 docs**: bind-mount your corpus and
  `docker compose exec app python -m scripts.ingest /path`, then
  `scripts.extract` for structured entries.

## Notes

- `pgserver` ships a glibc PostgreSQL build — the base must stay Debian/Ubuntu
  (`python:3.12-slim`), never Alpine.
- Speech-to-text defaults to **Groq Whisper** (needs the key, no download).
  Selecting a local faster-whisper model in the UI downloads it on first use
  into the container's ephemeral filesystem — lost on `down`. Mount a volume at
  `/home/app/.cache` to keep it.

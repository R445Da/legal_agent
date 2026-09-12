# Exporting the stack to another machine

The target needs Docker and nothing else — no Python 3.12, no `pgserver`, no
Ollama install, no corpus. Postgres, the embedding and reranker models, and a
seed database of 806 rulings are all inside the app image.

Decide one thing first: **where the chat model runs.**

| | Groq (default) | Local (`--profile local`) |
|---|---|---|
| needs | a `GROQ_API_KEY` and outbound HTTPS | ~3 GB more disk, ideally a GPU |
| bundle | app image only (~2.3 GB) | app + `ollama/ollama` + the model tag |
| works offline | no | yes, once the model is pulled |

Groq's API is geo-blocked from some networks (a Cloudflare 403 that comes and
goes, unrelated to the key). If the target is on such a network, export the
local profile or plan to route through a gateway.

## Option A — ship the source (smallest, rebuilds there)

Copy the repository without the build-context exclusions:

```
docker/  app/  scripts/  .streamlit/  streamlit_app.py
docker-compose.yml  .env.docker.example  EXPORT.md
```

`docker/seed.dump` (15 MB) must come along — it is the seed database. You can
leave out `data/` (the raw corpus, ~0.5 GB), `.pgdata/`, and `.venv/`; the
`.dockerignore` already excludes them from the image.

```bash
cp .env.docker.example .env.docker    # add GROQ_API_KEY, or the local block
docker compose up --build
```

The first build takes 5–15 minutes, almost all of it baking the ONNX models.

## Option B — ship the built image (no build on the target)

```bash
docker compose build app
docker save legal-rag:latest | gzip > legal-rag-image.tar.gz     # ~2.3 GB
```

For the local profile, add Ollama to the same bundle:

```bash
docker pull ollama/ollama:latest
docker save legal-rag:latest ollama/ollama:latest | gzip > legal-rag-bundle.tar.gz
```

On the target:

```bash
gunzip -c legal-rag-bundle.tar.gz | docker load
# copy docker-compose.yml and .env.docker.example alongside it
cp .env.docker.example .env.docker
docker compose up             # no --build — it uses the loaded image
```

## Carrying data across

Two volumes hold state worth moving. Neither is in the image.

**`pgdata`** — the archive. Skip this and the target re-seeds from
`docker/seed.dump` on first boot, which is what you want unless you have
ingested documents of your own.

```bash
# on the source
docker run --rm -v legal-rag_pgdata:/v -v "$PWD":/out alpine \
  tar czf /out/pgdata.tar.gz -C /v .
# on the target, before the first `up`
docker volume create legal-rag_pgdata
docker run --rm -v legal-rag_pgdata:/v -v "$PWD":/in alpine \
  tar xzf /in/pgdata.tar.gz -C /v
```

**`ollama-models`** — the pulled chat model. Same recipe with the volume name
swapped, or just re-pull on the target:

```bash
docker compose --profile pull up ollama-pull      # OLLAMA_PULL_MODEL to override
```

## Configuration on the target

| What | Where |
|---|---|
| Groq key, model choice, retrieval knobs | `.env.docker` |
| Local vs. remote chat model | `LLM_PROVIDER` in `.env.docker` + `--profile local` |
| Published ports | `APP_PORT`, `OLLAMA_PORT` (e.g. `APP_PORT=9000 docker compose up`) |
| GPU for Ollama | commented `deploy:` block in `docker-compose.yml` |

**Do not change** `EMBEDDING_MODEL`, `EMBEDDING_DIM`, or `TS_CONFIG`. The seed
vectors and the tsvector index were built with those exact values; changing one
means `scripts.ingest --reset` and `scripts.extract --reset` against your own
corpus.

## Verifying the target

```bash
docker compose ps                                  # app should report healthy
docker compose exec app python -m scripts.eval     # retrieval metrics
```

`scripts/check.sh` exercises the JSON API, which is not started by default —
see "Running the JSON API too" in [docker/README.md](docker/README.md).

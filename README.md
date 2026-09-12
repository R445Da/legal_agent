# Legal RAG

A Farsi-first RAG system with a voice/text **orchestration layer**: dictate or
type a court session and the system decides whether you're asking a question
(→ answer from the archive), filing new material (→ extract a structured
record, confirm, store), or asking for analytics (→ corpus stats + summary).

Runs with **zero external infrastructure**: `pgserver` boots a project-local
PostgreSQL + pgvector as your user, `fastembed` does local CPU embeddings, and
the LLM runs locally via Ollama. No API keys required.

The LLM and embedding model are `.env` changes, not code changes.

## Structure

```
app/
  main.py             FastAPI app + serves the web UI
  config.py           env-var settings (LLM, embeddings, API_TOKEN, CORS, DB)
  static/index.html   self-contained web UI (دستیار / Ask / Search / Eval / Bench / Library)
  db/
    models.py         Document + Chunk (pgvector) + Entry (structured record)
    engine.py         resolve_database_url() — embedded pgserver or external URL
  llm/
    base.py           LLMProvider interface (+ json_mode for structured output)
    anthropic_provider.py / openai_provider.py / local_provider.py
    factory.py        get_llm_provider() — the only place that picks a backend
    registry.py       showcase catalog: local (Ollama) + cloud (9router) models, resolve(id)
  rag/
    embeddings.py     fastembed wrapper, multilingual, e5 query/passage prefixes
    retriever.py      embed query -> pgvector cosine search -> top-k (+ scores)
    ingest.py         chunk -> embed -> store (shared by CLI and /ingest)
    pipeline.py       retrieve -> prompt -> generate -> RAGAnswer
    orchestrator.py   intent routing, structured extraction, related-doc linking
scripts/
  ingest.py           load *.txt from a directory
  extract.py          backfill structured Entry rows for every document
  eval.py             score the retriever against eval/*.jsonl
  serve.sh            start Ollama + the API
  tunnel.sh           expose the API on a public ngrok URL
data/farsi/           sample Farsi court-session summaries
eval/farsi.jsonl      retrieval eval set (query -> expected source docs)
```

## Setup

Requires Python <= 3.12 (`pgserver` constraint) and a local
[Ollama](https://ollama.com). If Ollama's site is blocked in your region,
extract the release tarball from GitHub and run `bin/ollama serve` from it.

```bash
uv venv --python 3.12
uv pip install -r requirements.txt
cp .env.example .env

ollama pull aya-expanse:8b        # multilingual LLM (good Persian)

python -c "import secrets; print(secrets.token_urlsafe(24))"   # put in .env as API_TOKEN
```

## Run

```bash
python -m scripts.ingest data/farsi     # load the sample corpus
python -m scripts.extract               # extract structured entries (uses the LLM, ~15s/doc)
scripts/serve.sh                         # Ollama (if local) + API on 0.0.0.0:8000
```

Open **http://localhost:8000/**. First request downloads the embedding model.

## Models (Farsi)

| Role | Default | Notes |
|---|---|---|
| LLM | `aya-expanse:8b` (Ollama) | Cohere multilingual, strong Persian. `qwen2.5:7b` also works. |
| Embeddings | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (384-dim) | Light. For best Persian retrieval swap to `intfloat/multilingual-e5-large` (1024-dim, `EMBEDDING_PREFIXES=1`), then `scripts.ingest --reset` + `scripts.extract --reset`. |

Changing the embedding model changes `EMBEDDING_DIM` → drop and rebuild:
`python -m scripts.ingest --reset` re-ingests, `python -m scripts.extract --reset` rebuilds the structured table.

### Switching models live + the showcase registry

`app/llm/registry.py` builds the catalog the UI switches between with no
restart: local models from Ollama plus cloud models from the **9router**
OpenAI-compatible gateway (`LLM_PROVIDER=openai`, `OPENAI_BASE_URL=http://localhost:20128/v1`,
`OPENAI_API_KEY=<9router key>`), and direct Anthropic models when
`ANTHROPIC_API_KEY` is set. `GET /models` returns it; the header dropdown picks
the active one; any request (`/ask`, `/assistant`, `/eval`, `/bench`) can carry
a `model` field with a registry id like `local::qwen2.5:7b` or
`openai::anthropic/claude-3-5-sonnet-20241022`.

Cloud routes only work once that upstream provider is connected in the 9router
dashboard — otherwise the gateway returns `No active credentials for provider`,
which the Bench grid shows per-cell. The free `combo` auto-router needs no setup.

## API

`/health` and `/` are open; everything else needs `Authorization: Bearer $API_TOKEN`.

| Method | Path | Purpose |
|---|---|---|
| GET  | `/health` | provider, model, index size |
| GET  | `/models` | the showcase registry — every local + cloud model, with `available` flags |
| POST | `/bench` | run the same questions through several models side by side (question × model grid + latency/token summary) |
| POST | `/assistant` | route one message: `query` \| `archive` (returns a draft) \| `analytics` |
| POST | `/assistant/commit` | write a confirmed archive draft (Entry + Document + related links) |
| GET  | `/stats` | corpus counts, top lawyers / topics / people / orgs |
| GET  | `/entries` · DELETE `/entries/{id}` | the structured records |
| POST | `/ask` | retrieve + generate → answer with cited excerpts |
| POST | `/search` | retrieval only (no LLM) — inspect what vector search returns |
| POST | `/ingest` · GET `/documents` · DELETE `/documents/{id}` | raw document archive |

Interactive docs at `/docs`.

## Measuring retrieval

```bash
python -m scripts.eval                # eval/farsi.jsonl, top_k=5
python -m scripts.eval -k 8 --ask     # also run the full pipeline per query
```

Reports `hit@1 / hit@3 / hit@k / MRR` and, for multi-doc questions, `cov@k`.
Swap `EMBEDDING_MODEL` in `.env`, re-run, compare — provider choice becomes
data instead of vibes. Relational questions ("which cases involve lawyer X")
score low on pure vector search — that's what the structured `Entry` table and
`/stats` are for.

## Serve it anywhere (public tunnel)

The web app is served by the API, so exposing the API exposes both:

```bash
ngrok config add-authtoken <token>   # one-time, from dashboard.ngrok.com
scripts/tunnel.sh                     # prints https://<id>.ngrok-free.app
```

Open that URL, or host a copy of `index.html` elsewhere and point it at the
tunnel via the ⚙ settings panel (server URL + `API_TOKEN`, saved in the browser).

## Not built yet / next steps

- **Speech-to-text** — the mic button is stubbed. Plan: local `faster-whisper`
  with a Persian model, `POST /transcribe`, hold-to-talk in the دستیار tab.
- **Chunking** is fixed-size windows; short docs become one chunk each.
- **Retrieval** is pure vector cosine — no metadata filters, no hybrid BM25.
- **Entity resolution** — extracted names aren't normalised, so "رضا کریمی"
  and "آقای رضا کریمی" count separately in `/stats`.
- **External Postgres** — set `DATABASE_URL` for anything past a laptop.

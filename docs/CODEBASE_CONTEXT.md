# Legal RAG MVP — Codebase Context for Analysis

Orientation document for an agent that needs to understand this codebase without
reading every file first. Written 2026-08-28 against the current tree. Verify
against source before relying on any specific line — treat this as a map, not a
spec.

---

## 1. What this project is

A **Farsi-first legal RAG system** with a thin **orchestration ("assistant")
layer** on top of a conventional retrieve-then-generate pipeline. A user types
(or dictates — STT is stubbed) a sentence in Persian; the system classifies it
into one of three intents and acts:

| Intent | Trigger shape | Action |
|---|---|---|
| `query` | a question | RAG pipeline: retrieve top-k chunks → LLM answer with `[n]` citations |
| `archive` | a past-tense narration of a court session | LLM extracts a structured record, returned as a **draft** (never auto-written); user confirms via a second endpoint |
| `analytics` | asks for counts / lists / overview | compute corpus stats from the structured table + optional LLM summary |

Design priorities, in order: (1) **zero external infrastructure** — embedded
PostgreSQL via `pgserver`, local ONNX embeddings via `fastembed`, local LLM via
Ollama, no API keys, works offline / behind geo-blocks; (2) **model choice is a
`.env` change, not a code change** — every LLM backend sits behind one interface
chosen in one factory; (3) **Farsi/Persian retrieval quality** (see the pinned
memory `farsi-language-requirement`).

It is an MVP / prototype. Several pieces are deliberately naive and flagged as
such in-code (chunking, retrieval, entity resolution).

---

## 2. The "agentic" flow — precise description

There is **no tool-calling agent loop, no ReAct, no planner, no multi-hop
reasoning.** The "agentic" part is a **single-shot intent router followed by a
fixed branch**. Be accurate about this when analyzing or extending it.

Entry point: `app/rag/orchestrator.py::run_assistant(session, llm, text, force_intent=None)`

```
run_assistant(text)
│
├─ intent = force_intent  (if the caller passed one — UI "mode" buttons)
│         else classify_intent(llm, text)          ← LLM call #1 (JSON, max_tokens=40)
│
├─ intent == "query":
│     answer_question(session, llm, text, top_k=5)  ← app/rag/pipeline.py
│        ├─ retrieve_scored()  → embed query, pgvector cosine search, top-5 chunks
│        └─ llm.generate(build_prompt(...), system=SYSTEM_PROMPT, max_tokens=1024)   ← LLM call #2
│     returns {intent, answer, contexts[], model, latency_ms}
│
├─ intent == "archive":
│     draft   = extract_entry(llm, text)            ← LLM call #2 (JSON, max_tokens=900)
│     related = find_related(session, text)         ← vector search, top-4 (no LLM)
│     returns {intent, draft, raw_text, related[], committed:false}
│     ── NOTHING IS WRITTEN. The client must call POST /assistant/commit ──
│
└─ intent == "analytics":
      stats = corpus_stats(session)                 ← pure SQL aggregation, no LLM
      if stats has entries:
        pull 20 most-recent Entry title+summary rows
        summary = llm.generate(question + listing, max_tokens=500)   ← LLM call #2
      returns {intent, stats, summary}
```

**The archive commit (second half of the archive flow):**
`orchestrator.py::commit_entry(session, draft, raw_text, source)` — called by
`POST /assistant/commit`:

1. `ingest_document(replace=True)` — stores `raw_text` as a `Document`, chunked +
   embedded, so the same material is retrievable by vector search.
2. `find_related(exclude_source=source)` — vector search for related existing docs.
3. Builds an `Entry` row (the structured record) with `related_ids` populated,
   commits it.

So one archived session ends up in **two tables**: `documents`/`chunks` (for
vector retrieval) and `entries` (for relational/structured queries that vector
search can't answer — "which cases involve lawyer X").

### LLM calls per assistant request
- `query`: 2 (classify + answer)
- `archive`: 2 (classify + extract); commit adds 0 LLM calls but re-embeds
- `analytics`: 1 or 2 (classify + optional summary)

### The prompts (all in `orchestrator.py` as module constants)
- `_INTENT_SYSTEM` — router. Few-shot with Persian examples. Falls back to
  `"query"` on any unparseable / invalid output (`classify_intent` last line).
- `_EXTRACT_SYSTEM` — fixed JSON schema for the structured record: `kind, title,
  summary, parties[{name,role}], representation[{lawyer,client}],
  events[{date,description}], entities{people,orgs,case_number,court,topic},
  tags[]`. Roles are romanized Persian enums (`khahan`, `khande`, `vakil_khahan`,
  `ghazi`, `mottaham`, `shaki`, `other`).
- `pipeline.py::SYSTEM_PROMPT` — "answer only from excerpts, cite `[n]`, reply in
  the question's language".
- analytics summary prompt — inline in `run_assistant`, "answer concisely in the
  question's language".

### JSON handling
No provider has reliable native structured output here. `json_mode=True` is
best-effort per provider (see §4). `orchestrator._parse_json()` is the safety
net: strips ``` fences, tries `json.loads`, then retries on the
first-`{`…last-`}` slice, then returns `{}`. `extract_entry()` then
**normalizes** the dict so the UI can trust the shape regardless of what the LLM
produced (coerces lists/strings, fills defaults).

---

## 3. Module map

```
app/
  main.py            FastAPI app, all routes, Pydantic schemas, bearer-token auth,
                     lifespan (create schema + construct the LLM provider once into app.state.llm)
  config.py          Settings from env (python-dotenv). NOTE: only some env vars
                     flow through here — see §5.
  static/index.html  Single-file web UI (~517 lines), RTL Persian. Tabs:
                     دستیار (assistant) / Ask / Search / Library. Talks to the API;
                     server URL + token configurable in a ⚙ panel, saved to localStorage.
  db/
    models.py        SQLAlchemy 2.0 declarative. Document, Chunk (pgvector Vector
                     column), Entry. EMBEDDING_DIM read straight from os.environ here.
    engine.py        resolve_database_url(): "embedded" → pgserver.get_server(.pgdata),
                     CREATE EXTENSION vector, return asyncpg URL. Else use the given
                     postgresql+asyncpg:// URL. create_schema() = create_all on startup.
  llm/
    base.py          LLMProvider ABC: async generate(prompt, *, system, max_tokens,
                     temperature=0.0, json_mode=False) -> LLMResponse; is_available().
                     LLMResponse: text, model, input/output_tokens, latency_ms, raw.
    factory.py       get_llm_provider() — THE ONLY place a concrete provider is chosen.
                     Reads LLM_PROVIDER + LLM_MODEL from os.environ.
    anthropic_provider.py  default model "claude-sonnet-4-6". json_mode = prefill "{".
    openai_provider.py     default "gpt-4.1". json_mode = response_format json_object.
                           Honors OPENAI_BASE_URL (Groq/Together/OpenRouter/vLLM).
    local_provider.py      default "qwen2.5:14b". Ollama /api/generate, json_mode =
                           {"format":"json"}. is_available() = GET /api/tags 200.
  rag/
    embeddings.py    fastembed TextEmbedding, lru_cache(1). e5 "query:"/"passage:"
                     prefixes toggled by EMBEDDING_PREFIXES (read from os.environ here,
                     default on). embed_passages (sync, ingest) / embed_query (async thread).
    retriever.py     retrieve_scored(): embed query → Chunk.embedding.cosine_distance
                     → ORDER BY distance LIMIT k. Returns [(Chunk, distance)].
                     similarity shown to user = 1 - distance.
    ingest.py        chunk_text(): naive fixed 900-char windows, 150 overlap; short
                     docs = 1 chunk. ingest_document(): dedupe by source, optional
                     replace, embed all pieces in a thread, store Document+Chunks.
                     Status: created|replaced|skipped|empty. Caller commits.
    pipeline.py      answer_question() — the RAG "query" path. build_prompt() numbers
                     excerpts [1..k]. Returns RAGAnswer(answer, sources, model,
                     latency_ms, contexts[]).
    orchestrator.py  everything in §2 + corpus_stats() + _norm_name() honorific-
                     stripping entity resolution.
scripts/
  ingest.py          python -m scripts.ingest [dir] [--reset]  — load *.txt (default data/cases)
  extract.py         python -m scripts.extract [--reset]  — backfill Entry rows for
                     every Document without one (runs extract_entry + find_related per doc)
  eval.py            python -m scripts.eval [path] [-k N] [--ask]  — retrieval eval
  serve.sh           start Ollama if needed + uvicorn on 0.0.0.0:8000
  tunnel.sh          ngrok http 8000
data/
  cases/*.txt        4 English common-law cases (Palsgraf, Hadley v Baxendale, etc.)
  farsi/*.txt        13 Farsi court-session summaries, contracts, legal opinions
eval/farsi.jsonl     retrieval eval set: {q, expect:[source-substr], kind, want_all?}
```

---

## 4. HTTP API (`app/main.py`)

`GET /` (UI) and `GET /health` are open. Everything else requires
`Authorization: Bearer $API_TOKEN` **iff** `API_TOKEN` is set (`require_token`
is a no-op when unset).

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | provider, model, `llm_available`, index sizes, `auth_required` |
| POST | `/assistant` | `{text, intent?}` → runs `run_assistant`. `intent` skips the router. 503 if LLM unavailable. |
| POST | `/assistant/commit` | `{draft, raw_text, source}` → `commit_entry` → `{id, title, document_id, related_ids}` |
| GET | `/stats` | `corpus_stats` — counts + top lawyers/topics/people/orgs |
| GET | `/entries` · DELETE `/entries/{id}` | structured records |
| POST | `/ask` | `{question, top_k}` → `answer_question`. 409 if nothing indexed, 503 if LLM down. |
| POST | `/search` | `{query, top_k}` → retrieval only, no LLM |
| POST | `/ingest` | `{documents:[{text,source,title?,metadata?}], replace?}` |
| GET | `/documents` · DELETE `/documents/{id}` | raw archive; delete cascades to chunks |

The LLM provider is constructed **once** at startup (`lifespan`) into
`app.state.llm`; every request reuses it. DB sessions are per-request
(`async_sessionmaker`).

---

## 5. Configuration — important inconsistency to know

Env is loaded by `app/config.py` via `python-dotenv`, but **not all env vars go
through `Settings`**. Three different modules read `os.environ` directly:

| Var | Read in | `Settings` field? |
|---|---|---|
| `LLM_PROVIDER`, `LLM_MODEL` | `config.py` **and** `llm/factory.py` (factory reads env directly) | yes (but factory bypasses it) |
| `EMBEDDING_MODEL` | `config.py` → used by `embeddings.py` | yes |
| `EMBEDDING_DIM` | `db/models.py` directly, `os.environ.get("EMBEDDING_DIM","384")` | **no** |
| `EMBEDDING_PREFIXES` | `embeddings.py` directly | **no** |
| `API_TOKEN`, `CORS_ORIGINS`, `DATABASE_URL`, `PG_DATA_DIR` | `config.py` | yes |

`config.py`'s `embedding_model` default is `BAAI/bge-small-en-v1.5` (384-dim,
English) while `db/models.py`'s `EMBEDDING_DIM` default is 384 and `.env.example`
proposes `intfloat/multilingual-e5-large` (1024). **`EMBEDDING_MODEL` and
`EMBEDDING_DIM` must be kept in sync by hand**; a mismatch fails at insert/query
time against the pgvector column. Changing either requires
`python -m scripts.ingest --reset` and `python -m scripts.extract --reset`.

### Current `.env` (the machine this runs on)
```
LLM_PROVIDER=local
LLM_MODEL=qwen2.5:3b                # fits 4GB VRAM; aya-expanse:8b better Persian but spills to CPU
LOCAL_LLM_URL=http://localhost:11434
API_TOKEN=<set>                     # tunnel is exposed, so token is required
EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
EMBEDDING_DIM=384
EMBEDDING_PREFIXES=0                # this model doesn't use e5 prefixes
DATABASE_URL=embedded              # pgserver into ./.pgdata
```
Reason on record: Groq and Google Gemini are geo-blocked from this network, so
everything runs locally and offline.

---

## 6. Data model detail

- **Document** — `id, source (unique-ish key, dedupe target), title, raw_text,
  doc_metadata (JSONB), created_at`. `chunks` relationship, cascade delete.
- **Chunk** — `id, document_id, text, embedding Vector(EMBEDDING_DIM), chunk_index`.
- **Entry** — the structured record. `document_id` (FK, `ON DELETE SET NULL`),
  `kind (session|note)`, `title, summary`, JSONB: `parties, representation,
  events, entities, tags, related_ids`, `raw_text`, `created_at`.
  `related_ids` holds **document ids** (see `find_related` return / `commit_entry`),
  despite the model comment saying "entry id" — worth double-checking if it matters.

`corpus_stats()` aggregates over all `Entry` rows in Python: counts topics /
people / orgs / lawyers, applying `_norm_name()` (strips honorifics like
`آقای`, `خانم`, `دکتر` and collapses whitespace) so `آقای رضا کریمی` and
`رضا کریمی` merge. This is the only entity resolution; extracted names are
otherwise unnormalized (a known gap).

---

## 7. Retrieval & evaluation

Retrieval is **pure vector cosine, top-k, no filters, no hybrid/BM25, no
rerank**. `retriever.py` has a TODO for metadata filters and hybrid search.

`scripts/eval.py` scores the retriever against `eval/farsi.jsonl`:
- `hit@1 / hit@3 / hit@k` — fraction of queries with ≥1 expected doc in top-k
- `MRR` — mean reciprocal rank of first expected doc
- `cov@k` — for multi-doc questions, mean fraction of expected docs retrieved
- `--ask` also runs the full pipeline and prints answers

Matching is substring: `expect` entries are matched against `Document.source`.
The README notes relational questions ("which cases involve lawyer X") score
low on vector search by design — that's the `Entry` table's job.

---

## 8. Running it

```bash
uv venv --python 3.12                     # pgserver needs Python <= 3.12
uv pip install -r requirements.txt
cp .env.example .env                      # then edit

ollama pull qwen2.5:3b                    # or aya-expanse:8b for better Persian
python -m scripts.ingest data/farsi       # load corpus
python -m scripts.extract                 # backfill structured entries (~15s/doc, uses LLM)
scripts/serve.sh                          # Ollama + API on :8000, UI at /
```

First request downloads the fastembed model. `python -m scripts.eval` to measure
retrieval. `scripts/tunnel.sh` for a public ngrok URL (token in `.env` is what
keeps it private).

---

## 9. Known gaps / "not built yet" (from README + in-code TODOs)

- **Speech-to-text** — mic button stubbed. Plan: local `faster-whisper` Persian
  model, `POST /transcribe`, hold-to-talk in the دستیار tab.
- **Chunking** — fixed 900-char windows only; no structure awareness.
- **Retrieval** — no metadata filters, no hybrid BM25, no rerank.
- **Entity resolution** — only honorific stripping; name variants over-count.
- **External Postgres** — set `DATABASE_URL` for anything beyond a laptop.
- **No tests** in the tree.
- **No migrations** — schema is `create_all` on startup; model changes need a
  manual drop/rebuild.
- **`EMBEDDING_MODEL` / `EMBEDDING_DIM` coupling** is manual and easy to get wrong (§5).
- The intent router has no confidence signal; ambiguous input silently
  defaults to `query`.

---

## 10. Where to look first for a given task

| Task | Start here |
|---|---|
| Change / add an LLM backend | `app/llm/factory.py` + a new `*_provider.py` implementing `base.py` |
| Tune intent routing | `orchestrator.py::_INTENT_SYSTEM`, `classify_intent` |
| Change the structured record schema | `orchestrator.py::_EXTRACT_SYSTEM` + `extract_entry` normalization + `db/models.py::Entry` |
| Improve retrieval | `rag/retriever.py`, `rag/embeddings.py`, `eval/farsi.jsonl` to measure |
| Change chunking | `rag/ingest.py::chunk_text` (shared by CLI + `/ingest`) |
| RAG answer prompt / citations | `rag/pipeline.py` |
| Analytics / stats | `orchestrator.py::corpus_stats`, `_norm_name` |
| API surface | `app/main.py` |
| UI | `app/static/index.html` (single file) |
| DB bootstrap / embedded Postgres | `app/db/engine.py` |

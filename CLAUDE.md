# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Farsi-first legal RAG system for Iran Insurance (the "insurance edition" — see `docs/INSURANCE-EDITION.md`, `docs/SYSTEM-GUIDE.md`, `docs/v3.md`). One engine (`app/`) with three front ends:

- **Streamlit** (`streamlit_app.py`, `app/ui/`) — the primary Persian RTL UI, 20 numbered sections (`app/ui/nav.py::SECTIONS`). It imports the engine directly; no API server needed.
- **React — «بیمه ایران حقوقی»** (`iran-insurance-legal/`) — a rewrite of every Streamlit section on top of the JSON API. Additive: nothing in the engine or Streamlit depends on it. Its server-side routes live in `app/iran_insurance_legal/` (`/legal/api/*`, SPA served at `/legal/`), wired by a short block at the bottom of `app/main.py`.
- `app/static/*.html` — frozen legacy UIs. Do not add features there.

## Commands

Python ≤ 3.12 is required (`pgserver`). Always use the venv binaries (`.venv/bin/python`, never bare `python`).

```bash
uv venv --python 3.12 && uv pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env                                   # LLM_PROVIDER=mock runs fully offline

.venv/bin/python -m scripts.seed_mock --reset --n 120  # deterministic 120-case insurance archive (+ data/laws/laws.json)
.venv/bin/streamlit run streamlit_app.py --server.port 8504
scripts/up.sh                                          # FastAPI on :8000 (Ollama/9router if configured)
scripts/legal-web.sh --offline                         # React UI on :5173 + API on :8000, mock LLM, own .pgdata-legal-web
scripts/legal-web.sh --build                           # build the React app and serve it at http://localhost:8000/legal/
scripts/doctor.sh                                      # diagnose servers / keys / network (see docs/RUNBOOK.md)
scripts/restart-ui.sh                                  # required after editing .env — processes keep the .env they started with
```

Tests and checks (CI runs exactly these, see `.github/workflows/docker.yml`):

```bash
.venv/bin/ruff check app scripts tests
.venv/bin/python -m pytest -q -m "not db"              # unit tests, no database
.venv/bin/python -m pytest -q -m db                    # needs a DB seeded by scripts.seed_mock
.venv/bin/python -m pytest tests/test_similar.py::test_name -q   # one test
.venv/bin/python -m scripts.ui_smoke                   # renders every Streamlit section headlessly
scripts/check.sh                                       # smoke-tests every API endpoint (BASE=... to target another host)
.venv/bin/python -m scripts.eval                       # retrieval metrics against eval/farsi.jsonl
.venv/bin/python -m scripts.demo_stages                # runs the demo stages (app/demo/stages.py) end to end

cd iran-insurance-legal && npm run typecheck && npm test && npm run build   # React: tsc, vitest, vite
```

`tests/conftest.py` pins the environment (mock LLM, `hash://384` embeddings, `PG_DATA_DIR=.pgdata-test`) before any `app.*` import, so `.env` never leaks into tests.

## Architecture

**LLM layer (`app/llm/`).** Nothing outside `app/llm/` imports a concrete provider — use `factory.get_llm_provider()` or `registry.resolve("provider::model")`. Every `generate()` takes `**knobs` and must silently ignore ones it does not support; `knobs.knobs_for()` says which controls a model accepts, and the UIs render one widget per knob. `mock` is a rule-based offline stand-in used by tests, CI and UI walkthroughs.

**Routing (`app/rag/orchestrator.py::route`).** One router for every UI: `query | law | cases | agent | archive | analytics | chat | unclear`. Keyword shortcuts skip the model (e.g. «ماده ۳۰ قانون بیمه…» → `law`); low-confidence `archive` becomes `unclear` rather than a guessed filing. A message naming a party the archive knows (`casebase.named_entities`) is routed to `cases` — before the model for short questions, after it for long ones so a dictated session is still filed — which needs `route(..., session=)`; without a session that shortcut silently does nothing. `run_assistant()` executes a routed message; `/legal/api/route` returns the intent without executing.

**Retrieval (`retriever.py`, `pipeline.py`, `catalog.search_entries`).** Chunk path: normalize_fa → embed → pgvector + Postgres FTS → RRF → optional cross-encoder rerank. Entry path: FTS over `Entry.text_search`, terms filtered by document frequency. Entries and chunks enter the prompt as one numbered `[n]` sequence — anything unnumbered is ignored by the system prompt, by design.

**Filing is a human-gated state machine (`app/rag/workflow.py`).** `classify → extract → references → timeline → similar → labels → commit`, persisted in `runs`/`run_steps` (`app/rag/runs.py`) so a reload or model failure loses nothing. Modes: `review` (one stop), `steps` (every gate), `auto`, `conversation` (`app/rag/conversation.py` asks for missing fields turn by turn). Nothing is written to the archive before `commit`; every LLM step has a deterministic fallback.

**Relational side is derived from entries.** `commit_entry` / `catalog.update_entry` call `casebase.sync_entry`, which rebuilds `legal_cases`, persons/organizations, case parties, citations (`legal_refs` via `lawbase`) and `graph_edges`. `POST /archive/resync` rebuilds all of it. The case views still fold entries with `cases.derive_cases()` and attach the `legal_cases` row as `record`.

**Conversations and entry editing (`conversations.py`, `entryedit.py`).** The chat is persisted in `conversations`/`messages` (not `st.session_state`), and `assistant_answers.conversation_id` links answers to their thread. Each conversation has a `focus` — `{kind, id, label}` of the record it is working on, set when an edit is confirmed and shown in the thread list; nothing reads it back to resolve follow-ups like «نشانش بده» yet. Editing is propose-then-confirm: the agent tools `propose_edit`/`propose_append` (`tools.py`) only return a current-vs-new proposal; `entryedit.apply` → `catalog.update_entry` is the single writer, so the case, parties, citations, graph and vault re-sync. HTTP: `/conversations[/{id}]`, `POST /entries/{id}/propose` and `/apply`. Both UIs render the edit gate and share the thread table: Streamlit's assistant (`app/ui/views/agent.py`) writes turns in-process, React through `POST /legal/api/conversations` and `/legal/api/conversations/{id}/messages` (plus `PUT …/focus`).

**Other subsystems.** `provenance.py` persists answers with an evidence ledger (`/answers`); `hooks.py` signed outbound webhooks and `ci.py` inbound CI events; `vaultsync.py`/`vaultmap.py` export the archive as an Obsidian vault under `graphify-out/obsidian/آرشیو/` (section ۲۰ draws it via `/graph/vault`).

**React front end (`iran-insurance-legal/src/`).** The API is the authoritative store; the browser never mutates archive state except through confirmed API calls. `api/` (typed client + TanStack Query; `['state']` mirrors Streamlit's `data.load()` via `/legal/api/state`), `assistant/runtime.ts` (navigation → `/legal/api/route` → executor; filings go to `/runs` and stop at workflow gates rendered by `RunCard`; an agent answer's `pending_edit` stops at `EditGate`, and only `confirmEdit` calls `/entries/{id}/apply`), `state/` (zustand: shell tabs + deep links `#/s/<section>/<tab>/<record>`, settings = the Streamlit left panel), `sections/` (one file per Streamlit section, registry in `sections/registry.ts`). Every turn is written to the persisted thread (`assistant/turns.ts` maps message ⇄ turn); a thread can be reopened in either UI, so a turn written from React also carries the keys Streamlit's `_render` reads (`run_id`, `pending_text`, `kind`) — `_render_pipeline` raises on an archive turn without `run_id`. A proposal on a reopened turn is shown but never applied: the record may have changed since. RTL-first: use logical Tailwind classes (`ms-/me-/ps-/pe-/start-/end-`) and route every number through `lib/format.ts::fa()`.

## Gotchas

- Config is read from `os.environ` in several modules at import time, not only `app/config.py` (`EMBEDDING_DIM` in `db/models.py`, retrieval toggles `HYBRID`/`RERANK`/`RRF_*` in `retriever.py`, `ROUTER_MODEL` in the orchestrator). `EMBEDDING_MODEL`, `EMBEDDING_DIM` and `EMBEDDING_PREFIXES` must agree; changing them needs `scripts.reembed` (or `ingest --reset` + `extract --reset`).
- An existing database (`.pgdata`, `.pgdata-legal-web`, a restored dump) needs `scripts.migrate_conversations` once: `create_all` adds the chat tables but not `assistant_answers.conversation_id`, and ORM queries on `assistant_answers` fail on the missing column without it.
- `docker/seed.dump` predates newer columns/tables: after restoring it run `scripts.migrate_fts`, `scripts.migrate_runs` **and** `scripts.migrate_conversations`. Schema changes otherwise rely on `create_all` (no migrations).
- Streamlit: the engine is async, Streamlit is not — go through `app/ui/aio.py` (one long-lived loop) and build cached resources on the script thread (`resources.init()`), never lazily inside a coroutine. After any write call `data.refresh()`. Latin digits in the UI are a bug (`theme.fa_num`). Never put `direction: rtl` on `stAppViewContainer`.
- Extraction is model output: string fields arrive as lists and vice versa — normalise (`cases._as_strings`, `utils.asText` in React) before rendering.
- `.env` holds live keys (gitignored) — never print it or commit it.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).

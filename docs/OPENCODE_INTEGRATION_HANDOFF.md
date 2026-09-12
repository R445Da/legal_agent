# OpenCode Integration — Session Handoff / Resume Guide

**Goal of this work:** add OpenCode (the AI coding agent — "me", this session)
as a feature inside your existing **Legal RAG** FastAPI app so it can work with
your RAG pipeline.

**OpenCode session ID (this conversation):** `ses_f9bebfea5ffeaPnXmdA7gST95f`

---

## How to resume THIS conversation exactly where it left off

From a fresh terminal, run:

```bash
cd ~/Documents/coding/ragflow/legal-rag-ui-workbench
opencode --session ses_f9bebfea5ffeaPnXmdA7gST95f
```

> If `--session` doesn't resume (older flag), try the interactive picker:
> `opencode` → New Session → pick the session titled **"Model setup status check"**.
>
> A full JSON transcript was also exported beside this file:
> `docs/OPENCODE_INTEGRATION_SESSION.json` (generated via `opencode export`).
> It can be reimported with `opencode import <file>` if the live session is lost.

### Cheat sheet — resume an OpenCode conversation
- `opencode session list` → see all session IDs
- `opencode export ses_…` → dump a session to JSON (resume/backup)
- `opencode import <file.json>` → restore a session from a JSON export
- `opencode run -m opencode/big-pickle "…"` → run one headless task (works now)

---

## The exact decision point we reached (read this first)

Your RAG system is at `~/Documents/coding/ragflow/legal-rag-ui-workbench/`.
It follows one hard rule (from `CLAUDE.md`): **nothing outside `app/llm/` may
import a concrete provider** — every model is a plugin implementing
`LLMProvider` (`app/llm/base.py`: `async generate(...)` → `LLMResponse`), chosen
via `.env` (`factory.py`) and switchable at runtime via `registry.py`. The
orchestrator relies on `json_mode=True` for intent routing + structured `Entry`
extraction, and expects a **single-turn chat completion** returning text.

**Key tension:** OpenCode is an *agent* (takes actions: file ops, terminal, web,
multi-tool reasoning over a long horizon) — NOT a plain one-shot completion
endpoint. That shapes how we wire it in.

I asked you which shape you wanted, and you replied:

> *"can you save the exact details of this chat so i can also come back to and
> create another instance of so i can continue it after i have really saved
> everything and gotten out of this terminal"*

**So: no code was written yet.** Saving/resume was the priority. When you
return, we continue at this decision point.

---

## The proposed integration option (what we were about to build)

I recommended **Option A** (matches your earlier pick: *"Agent tools usable in
RAG pipeline"*):

### Option A — OpenCode as a drop-in `LLMProvider` plugin
1. Create `app/llm/opencode_provider.py` implementing `LLMProvider`, where
   `generate()` shells out to:
   ```bash
   opencode run -m <model> "<prompt>"
   ```
   I already verified this works headless with your free models — it returned
   clean text output in seconds. For JSON use add `--format json` + an
   instruction.
2. Register it in `app/llm/factory.py` (`_PROVIDERS["opencode"]`) and in
   `app/llm/registry.py` so it appears in the UI dropdown.
3. `.env`: `LLM_PROVIDER=opencode`, `LLM_MODEL=opencode/big-pickle`.
4. Result: `/ask`, `/assistant`, `/eval`, `/bench` all get agentic power with
   **zero changes elsewhere** in the pipeline (it respects the architecture
   rule).

**Con:** it inherits the orchestrator's constraints — `json_mode` intents need
reliable JSON from the agent; agent tool-calling makes latency higher than a
plain completion. It treats the whole agent as a generator.

### Option B — Dedicated `/agent` endpoint (coding-agent use case)
Add a new `/agent` route that runs `opencode` with `--dir` pointed at a
workspace, returning the agent's full result (file changes / commands).
This is the "opencode the coding agent embedded in my web app" case (the RAG
QA vs. real software work distinction).

### Option C — Both A and B.

---

## Facts & context gathered this session (useful for continuing)

- **Your available free models** (via `opencode models`):
  `opencode/big-pickle` (this session's model),
  `opencode/ling-3.0-flash-fin-free`,
  `opencode/mimo-v2.5-free`,
  `opencode/muse-spark-1.2/-1.3-contributor-free`,
  `opencode/nemotron-3-ultra-free`,
  `opencode/nemotron-3.5-lightning-free`.
- **Fastest free** ≈ flash/free tier (`ling-3.0-flash-fin-free`,
  `muse-spark-1.3-contributor-free`). No single objective "best"; Big Pickle and
  Nemotron-3.5-lightning are the capable ones.
- **`opencode run` headless works** and is the cleanest way to call OpenCode
  from Python/FastAPI (subprocess). Server+SDK (`@opencode-ai/sdk`) is the
  heavier alternative for streaming/concurrency.
- **`opencode web`** = full agent as a web app in the browser (built-in; the
  "opencode agent inside a web app" question) on `127.0.0.1` (set
  `OPENCODE_SERVER_PASSWORD` to expose on network).
- **MCP note:** OpenCode exposes its own tools over MCP for OpenCode to *use*
  external tools — not the reverse direction; not what we need here.

### Your RAG architecture (relevant files)
- `app/main.py` — FastAPI routes: `/ask`, `/search`, `/assistant`,
  `/assistant/commit`, `/eval`, `/bench`, `/models`. All token-gated except
  `/health`, `/`.
- `app/rag/pipeline.py` — `answer_question()` (RAG endpoint path).
- `app/rag/orchestrator.py` — `run_assistant()`: intent routing (query /
  archive / analytics) → dispatches; uses `classify_intent()`,
  `extract_entry()` (strict JSON, `ENTRY_SCHEMA`), `find_related()`,
  `commit_entry()`.
- `app/llm/` — `base.py` (ABC `LLMProvider`, `LLMResponse`), `factory.py`
  (`_PROVIDERS = {anthropic, openai, local}`), `registry.py`
  (`<provider>::<model>` ids, curated 9router gateway),
  `openai_provider.py` / `anthropic_provider.py` / `local_provider.py`.
- `app/config.py` — env-driven (token, CORS, DB, embeddings).
- Stack: Farsi-first RAG, FastAPI, embedded Postgres (pgserver) + pgvector,
  fastembed (CPU), rerank cross-encoder, default LLM local Ollama; also uses a
  separate `.9router` LLM router, `codebases/llm`, and `rag-server.log` shows
  the live `/search`, `/ask`, `/assistant` traffic.
- Reusable cmd: `opencode run -m opencode/big-pickle "<task>"` confirmed OK.

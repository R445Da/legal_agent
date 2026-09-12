# Legal RAG — system guide

Written 2026-09-03, against the working tree. It describes what the system is,
how each part actually behaves, what changed recently and why, and where the
real weaknesses are. Read it before changing retrieval, the prompt, or the UI.

Companions: `CODEBASE_CONTEXT.md` (older, still broadly right about the engine),
`PORTING-GROQ-AND-REASONING.md` (the Groq/reasoning handoff), and the repo-root
`CLAUDE.md` (rules for model sessions).

---

## 1. What the system is

A Farsi-first legal archive with retrieval-augmented answering. One message is
routed to one of three intents:

| intent | what happens |
|---|---|
| `query` | retrieve from the archive, generate a cited answer |
| `archive` | extract a structured record from dictated/typed text, show it, store on confirm |
| `analytics` | aggregate the structured table, summarise in words |

It runs with no external infrastructure by default: `pgserver` boots a
project-local PostgreSQL + pgvector into `.pgdata/`, `fastembed` does CPU
embeddings, and generation can be a local Ollama model. Cloud models are a
config choice, not a code change.

**Streamlit (`streamlit_app.py`) is the front end.** `app/main.py` still serves
the JSON API for scripts and tunnels, and `app/static/app.html` is frozen legacy
— do not add features there.

---

## 2. The shape of the data

Four tables (`app/db/models.py`):

```
Document   one ingested text          source (unique key), title, raw_text, doc_metadata
  └─ Chunk   ~900-char window          embedding (pgvector), text, text_search (tsvector)
Entry      structured record           title, summary, parties, representation, events,
                                       entities, tags, raw_text, text_search (tsvector)
Label      a human judgment            relevance / tag / review
```

The distinction that matters:

- **Chunks** answer *"what does the archive say about topic X"*. Semantic.
- **Entries** answer *"which cases involve person X"*. Relational. Vector search
  is bad at this, which is the entire reason the Entry table exists.

`Entry.raw_text` is also ingested as a `Document`, so the same material is
reachable both ways.

**Cases are derived, not stored.** `app/rag/cases.py::derive_cases()` folds
entries by `entities.case_number` into the case objects the UI shows. An entry
with no case number becomes its own case and is flagged `incomplete`, which is
what fills the human-review queue.

---

## 3. Retrieval

### 3.1 The chunk path — `app/rag/retriever.py`

```
query → normalize_fa → embed
                    ├── pgvector cosine  (RETRIEVE_CANDIDATES per side)
                    └── Postgres full-text over chunks.text_search
                    → fuse with Reciprocal Rank Fusion (RRF_LEX_WEIGHT)
                    → cross-encoder rerank of the top RERANK_TOP
                    → top_k
```

Every stage is env-toggled and read from `os.environ` at import in each module,
*not* through `app/config.py`: `HYBRID`, `RERANK`, `RETRIEVE_CANDIDATES`,
`RERANK_TOP`, `RERANK_MODEL`, `RRF_LEX_WEIGHT`, `RRF_K`, `TS_CONFIG`.
`retrieve_scored(...)` also takes per-call overrides for all of them, plus a
`trace` dict that receives per-stage milliseconds — that is what the UI's
latency bar reads.

### 3.2 The entry path — `app/rag/catalog.py::search_entries()`

`Entry.text_search` is a stored `tsvector` over title + summary + raw_text with
a GIN index. Two things about it are load-bearing:

**Persian folding must match on both sides.** The column is built through
Postgres `translate()`, whose arguments are derived from the *same* character
table `normalize_fa` uses — `textnorm.sql_translate_args()`. An Arabic yeh
stored on disk therefore matches a Persian yeh typed into the box, and the two
sides cannot drift because there is one source.

**Terms are filtered before ranking.** `TS_CONFIG` is `simple`, which has **no
stopword list** — Postgres ships no Persian configuration — so «پرونده» and
«دادگاه» weigh exactly as much as «معیوب», and `ts_rank_cd` alone returns the
same short entries for every question. So: count how many entries each term
appears in, drop the terms present in more than half the archive, then rank what
remains. If everything is either absent or ubiquitous, fall back to the rarest
term that matches at all.

Measured on the current 16-entry archive:

| question | result |
|---|---|
| «در پرونده کالای معیوب…» | 4 entries, correct one first |
| «پرونده‌های آقای کریمی» | 8 entries, all mentioning him |
| «چند پرونده کارگری داریم؟» | 2 entries, labour tribunal first |
| «پرونده کلاسه ۱۴۰۲۱۱۲۲» | 1 entry, exact |

### 3.3 Embeddings — the dimension is baked into the schema

`EMBEDDING_DIM` is read directly from `os.environ` by `db/models.py`, bypassing
`config.py`. Changing `EMBEDDING_MODEL` to one of a different width requires
updating `EMBEDDING_DIM` **and** `EMBEDDING_PREFIXES` (1 for the e5 family, 0
for bge / paraphrase-multilingual), then `scripts.ingest --reset` and
`scripts.extract --reset`. A mismatch surfaces as an opaque insert/query error
against the fixed-width pgvector column, not a clear message.

---

## 4. The prompt — the part that silently decides everything

`app/rag/pipeline.py`:

```python
SYSTEM_PROMPT = (
    "Answer using only the provided excerpts. Cite the excerpt number in "
    "brackets like [1] for every claim. If the excerpts don't support an "
    "answer, say so explicitly. Reply in the same language as the question…"
)
```

**Anything not inside the numbered excerpts is invisible to the model, by
instruction.** This caused a long-running bug: matched entries were prepended to
the prompt as an unnumbered preamble, and the model correctly answered
"excerpts [1]–[5] contain nothing about him" — while eight entries naming him
sat right above. It was obeying.

The fix, and the rule to keep:

- `format_source(kind, title, body, meta)` renders **every** piece of evidence
  the same way — `(مدخل)` for an entry, `(سند)` for a chunk.
- `build_prompt()` numbers them all in **one** `[1]..[n]` sequence.
- Entries come first: they answer relational questions that chunks cannot.
- `snippet(text, terms)` includes the passage that actually matched, so an entry
  matched on something buried in its body shows *why* it matched.

`build_prompt` accepts plain strings as well as Chunk objects, which is what
lets the two kinds of source be mixed.

---

## 5. The LLM layer

**Nothing outside `app/llm/` may import a concrete provider.** Call
`get_llm_provider()` (`factory.py`) or `registry.resolve(model_id)` and depend
only on the `LLMProvider` ABC.

```
base.py             generate() + stream() + is_available() → LLMResponse
factory.py          _PROVIDERS = {anthropic, openai, groq, local}
groq_provider.py    Groq's deviations, see below
openai_provider.py  any OpenAI-compatible endpoint via OPENAI_BASE_URL
local_provider.py   Ollama
registry.py         the catalog the UI switches between, id = "provider::model"
knobs.py            which tuning controls each model accepts
```

### 5.1 Groq's three deviations

1. **`max_completion_tokens`, not `max_tokens`** — and that budget covers hidden
   reasoning *plus* the answer. Too small a value on a reasoning model returns
   empty content with `finish_reason="length"`.
2. **A real `User-Agent`** — Groq sits behind Cloudflare, which answers the
   stdlib default with `HTTP 403: error code: 1010`.
3. **`/models` is authoritative** — never inject a hardcoded default the gateway
   did not report. `llama-3.3-70b-versatile` 404s on this key.

Filter non-chat ids (`whisper`, `tts`, `orpheus`, `prompt-guard`, `-guard-2`,
`embed`) out of the chat dropdown.

### 5.2 Knobs are data, not conditionals

`reasoning_effort` is valid on Groq gpt-oss and Qwen3 and a **400** on `llama-*`,
`allam-*`, `groq/compound*`. Rather than teach call sites which backend they are
talking to, `knobs_for(provider, model)` returns the controls a model accepts,
`registry.catalog()` attaches them to every entry, and the panel renders one
widget per knob. Switch model, the panel changes.

**Every provider's `generate()` takes `**knobs` and must silently ignore what it
does not support.** That is what makes a mixed `/bench` grid work.

### 5.3 Streaming

`stream()` yields `{"type": "reasoning" | "answer" | "done", …}`. The base class
implements it by calling `generate()` and emitting the result in one piece, so a
backend that cannot stream still works everywhere. `LocalProvider` overrides it
(Ollama's newline-delimited JSON) and `OpenAIProvider`/`GroqProvider` override it
(SSE deltas, reading **both** `delta.reasoning` and `delta.reasoning_content` —
providers disagree on the name).

`aio.iterate(agen)` drives an async generator from Streamlit's synchronous
script, and closes it on the shared loop in a `finally`: an HTTP stream abandoned
inside an async generator is finalised later on the wrong loop and surfaces as
*generator didn't stop after athrow()*.

---

## 6. Speech to text

`app/rag/transcribe.py`. Selectable backends, best first:

| choice | notes |
|---|---|
| `groq:whisper-large-v3-turbo` | **default when a Groq key exists** — fastest, best Persian |
| `groq:whisper-large-v3` | most accurate |
| `local:large-v3 … tiny` | faster-whisper, CPU, offline, individually cached |

Picked in the left panel, since it is a setting rather than a per-message
choice. In the chat, recording *is* sending: stop the recording and the
transcript is submitted as the message.

---

## 7. The UI

### 7.1 Layout

```
[ model + retrieval ]      [ content ]      [ ۰۱..۱۴ sections ]
   app/ui/sidebar.py                          app/ui/nav.py
        left                                       right
```

Both panels are **pinned columns, not `st.sidebar`**. Streamlit removes the
sidebar's expand control from the DOM once collapsed, and no Python API reopens
it — the panel becomes permanently unreachable. Collapsed, each panel goes to
width 0 and leaves only a fixed handle against the screen edge. Nothing runs
across the top.

The fourteen sections: دستیار پرونده · داشبورد · پرونده‌ها · رویدادها ·
بایگانی سند جدید · جستجو و پرسش · تیکت‌ها (اسناد) · طبقه‌بندی و برچسب‌ها ·
بازبینی انسانی · برچسب‌گذاری و بازخورد · آمار آرشیو · ساختار داده و خط لوله ·
ارزیابی بازیابی · مقایسهٔ مدل‌ها.

### 7.2 The async bridge — read before touching the UI

The engine is async; Streamlit is synchronous and re-runs the script on every
interaction. `asyncio.run()` per call creates and destroys a loop each time, and
a cached `AsyncEngine` holds asyncpg connections bound to the loop that created
them — the second interaction dies with *Future attached to a different loop*.

So: **one long-lived event loop on a daemon thread** (`app/ui/aio.py`), and
`aio.run(coro)` submits to it. Two rules keep it working:

1. **Build cached resources on the script thread, never lazily from inside a
   coroutine.** `resources.init()` runs at the top of `main()` because `_build()`
   itself calls `aio.run()` — reaching it from a coroutine already on the loop
   blocks the loop's own thread waiting on itself. That deadlock hangs the
   request forever with no error.
2. **`_build()` is keyed on `id(aio.loop())`.** Hot reload re-imports `aio` and
   starts a fresh loop while `st.cache_resource` survives, leaving an engine
   bound to a dead loop. Keying on loop identity rebuilds it transparently.

### 7.3 Design

The look is a **legal ledger**, ported verbatim from the `<style>` block of
`app/static/app.html`: warm paper `#F3F0E7`, tan rules `#E1DAC7`, forest teal
`#0F4C3A`, stamp red, gold, IBM Plex Mono numerals, a two-layer shadow.
`app/ui/theme.py` owns both palettes and the component vocabulary: `ledger()`,
`panel()`, `stamp()`, `case_id()`, `timeline()`, `card()`, `chips()`, `kv()`,
`answer()`. Use these rather than bare `st.write` — approximating the design
produces a generic dashboard.

**The record is the control.** No «مشاهده» button beside a row: `components.row()`
after `components.rowlist_start()` renders the whole record as one clickable
full-width button. A side button also forces a column split, which is what made
lists ragged. A clicked name or tag opens its results **in place** — those names
were extracted from the entries, so the system already knows the answer and must
not send the user back to a search box.

### 7.4 Traps that have bitten repeatedly

- **Latin digits are a bug.** Route every number through `theme.fa_num()`.
- **You cannot assign to a widget's own key after the widget exists.** Park the
  value elsewhere and apply it at the top of the next run.
- **`st.cache_data` returns a fresh copy each run**, so dicts are unusable as
  `selectbox` options. Use ids and look the object up.
- **`esc()` only with `unsafe_allow_html=True`.** In plain Markdown it renders
  `&lt;` and `&amp;` as visible text.
- **Exempt icon elements from the font override.** A blanket
  `* { font-family: Vazirmatn }` makes Material icons print their code points as
  words — match `[data-testid*="Icon"]`, not just `stIconMaterial`.
- **Never put `direction: rtl` on `stAppViewContainer`.** It breaks Streamlit's
  own width arithmetic. Put it on `[data-testid="stHorizontalBlock"]` to flip
  column order, and on content elements for text.
- **Extraction is model output.** Fields typed as strings arrive as lists;
  `events` and `parties` hold dicts most of the time and bare strings the rest.
  `cases.py::_as_strings` and `agent.py::_label_event/_label_party` normalise
  them. Without that you get `unhashable type: 'list'` screens away.

---

## 8. What changed recently, and why

Grouped by cause, because the *why* is the reusable part.

### Groq and models
- `GroqProvider` added and registered; `LLMResponse.reasoning`; `knobs.py`;
  registry generalised to iterate multiple gateways with `/models` treated as
  authoritative and a real User-Agent.
- Streaming added end to end — Ollama NDJSON, Groq/OpenAI SSE including live
  reasoning deltas.
- Default switched to `groq::openai/gpt-oss-20b` (backup at `.env.bak`).

### Failure handling in the chat (added after a real incident)

When a model call fails mid-message the chat used to lose the text, crash, and
retry the failing call on every rerun until the app looked dead. Now:

- `agent.py::_answer_pending` **pre-flights** the selected model — if the sidebar
  entry is `available: false` the turn is marked failed immediately with a
  Persian reason, no doomed call.
- a failure during routing/extraction/answering stores `turn["error"]` and
  `turn["answered"]` on the message; it renders as an error bubble with a
  **تلاش دوباره** button and is **never re-attempted automatically**.
- `sidebar.py` lands on a model that actually works: if the stored pick or the
  configured default is `available: false` but something else works, it switches
  and shows «... در دسترس نیست — به ... تغییر داده شد».

Note the local-model `available` flag only checks that Ollama's HTTP server
answers, not that inference works — a broken Ollama install (missing
`llama-server` binary) still shows models as available and 500s on every call.
That path is caught by the failure handling above, not prevented.

### Routing (Phase 1)

`orchestrator.route(llm, text, forced=)` is the one router now — both the
Streamlit chat and FastAPI `/assistant` call it, and the executors (`agent.py`
streamed, `run_assistant` a dict) share the vocabulary.

Five intents, not three:

| intent | what happens |
|---|---|
| `query` | RAG answer from the archive |
| `analytics` | corpus counts / lists |
| `archive` | extract an Entry draft — **only** when the user is recording events, not asking about them |
| `chat` | conversational reply, no retrieval, nothing stored — greetings, tasks, meta |
| `unclear` | show a clarifying question + quick-reply buttons; route nothing yet |

The old fallback default was `archive`, which is why stray text became proposed
Entries. Now: high-precision shortcuts (greeting, count word) skip the model;
everything else is classified with confidence; `archive` below ~0.55 confidence,
or an explicit `unclear`, becomes a clarification instead of a guess.

`ROUTER_MODEL` (env) pins the classifier to a fast model — default
`groq::openai/gpt-oss-20b` — so routing stays quick when the answer model is a
large reasoning one. Unset = use the answer model.

### The entry-building pipeline (`app/rag/workflow.py`)

The `archive` intent is a **six-step resumable state machine**. How often it
stops for the user is `WorkflowState.mode`, chosen with the **حالت ثبت مدخل**
selector beside the composer:

- `review` (default) — run everything, stop **once** at a consolidated review
  panel that only prompts for fields that came back empty (`_missing_required`)
- `steps` — stop at every gate (extract, timeline, similar, labels)
- `auto` — stop for nothing; extract → derive → commit

| step | what it does | cost |
|---|---|---|
| `classify` | **no LLM call** — records that the router (upstream) already chose `archive` | ~0 |
| `extract` | `extract_entry()` — the one unavoidable model pass | ~25-40 s |
| `timeline` | orders `events` into editable rows; the approved list is written back into `events` | ~0 |
| `similar` | **one** `search_entries` pass (was a dozen DF queries); `find_related` only if that found <4; tool-loop trail off unless `SIMILAR_TOOL_BUDGET_S` | ~0 |
| `labels` | **no LLM call** by default — extracted `tags` + keyword match vs. the taxonomy, all through `taxonomy._clean`; `LABELS_LLM=1` re-enables the model proposal | ~0 |
| `commit` | `commit_entry(related=…)` → `Entry` (+ Document + chunks) + `Entry.related` + `Label` rows | ~2 s |

So a default `review` run on `qwen2.5:3b` is **~30 s and one approval**.

Every step and the full `WorkflowState` are persisted to `runs` / `run_steps`
(`app/rag/runs.py`). A reload or a model failure loses nothing; a failed step
retries in place (`advance(run_id)` with no patch). **Every LLM-driven step has
a deterministic fallback** — a 3B model returning junk JSON must not stall the run.

LangGraph-shaped on purpose (state = dataclass, steps = pure-ish nodes, gate =
`interrupt()`, tables = checkpointer) so it can be swapped without rewriting the
step bodies — but no dependency today.

The **build console** is `GET /runs/view` on the API server (`localhost:8000`,
read-only, opens like `/app`; its fetches carry `?token=`). It shows every run's
steps, the model's proposal vs. the user's edit, timings, and the `similar`
step's tool calls. `GET /runs`, `/runs/{id}`, `/runs/{id}/events` (SSE) are the
JSON behind it.

### Tool calling (Phase 2 — done for context-gathering)

`LLMProvider.generate(tools=[...], tool_choice=)` on every provider;
`LLMResponse.tool_calls` is the normalised `[{id, name, arguments}]`.
`LocalProvider` uses Ollama's `/api/chat` **only** when `tools` is passed — the
`/api/generate` path (every other call) is untouched. `tools` and `json_mode`
don't combine.

`app/rag/tools.py` exposes **read-only** tools (`search_entries`, `find_related`,
`get_document`, `corpus_stats`) — `commit_entry` is deliberately not a tool.
`run_with_tools()` is the loop: generate → dispatch → feed results back as plain
text → generate, bounded by `max_rounds`. It works with any model that fills
`tool_calls` (local ones included) because it never needs a multi-turn `chat()`
method. Used in the `similar` step, and available to the `query` path behind the
«نوع پیام» selector.

### Retrieval and prompting
- Entries enter the prompt as **numbered, citable excerpts** — the single most
  consequential fix.
- `Entry.text_search` tsvector + GIN index; `scripts/migrate_fts.py` extended and
  run (7475 chunks, 16 entries populated).
- `search_entries()` rewritten: term filtering by document frequency, then
  `ts_rank_cd`. A hand-written stopword list was tried and removed — it could not
  keep up («تصمیمی» matched 0 entries and killed the AND; «گرفت» matched 8/16 and
  buried «معیوب»).
- `snippet()` shows the passage that matched.

### UI
- Rebuilt as fourteen Persian RTL sections on the ledger design; two collapsible
  panels; clickable record rows; light/dark; the chat page with an inline mic.
- Speech-to-text model selection, defaulting to Groq Whisper turbo.

### Bugs fixed (each was mistaken for a quality problem at least once)
- **Stale code**: `runOnSave = false` meant the running server never picked up
  any edit. Hours of "it still does the same thing" were this.
- Async-bridge deadlock; loop-identity cache key.
- Empty answers rendering as a blank bubble ("the reply vanished") — now the
  reasoning is shown expanded with an explanation.
- `esc()` without `unsafe_allow_html` leaking HTML entities.
- Crash on non-dict events/parties.
- Icon font override printing `keyboard_arrow_down` / `check` as text.

---

## 9. Where this system is actually weak

Honest list, most consequential first.

1. **The eval measures half the system.** `scripts/eval.py` (and `run_eval`) only
   exercise **chunk** retrieval. Current numbers: **hit@1 0.412, cov@5 0.083** —
   and the failures are exactly the relational questions that `search_entries`
   now answers well but the eval never calls. Extending `run_eval` to score entry
   matches is the highest-value next change: until then you are tuning blind on
   half the pipeline.

2. **806 court rulings dilute a 16-entry archive.** The playbook's hit@1 0.88 was
   measured before that corpus was added. A name query competes against 7475
   chunks of unrelated rulings. Consider scoping retrieval by collection by
   default, or weighting notes above bulk rulings.

3. **The reranker dominates latency.** Roughly 4 seconds at `RERANK_TOP=12`
   versus 244ms with rerank off, and cost is linear in `RERANK_TOP`. It is also
   the biggest quality lever, so trade it deliberately with the Search tab's A/B
   and the Eval tab's sweep.

4. **No entity resolution.** «رضا کریمی» and «آقای رضا کریمی» count separately in
   stats and match separately in search.

5. **Chunking is fixed-size windows.** It cuts mid-sentence and ignores legal
   structure (ماده، بند، تبصره).

6. **No tool calling.** The model receives everything and decides. Letting it
   choose between "search entries" and "search documents", or scope to a
   collection, is the natural next step — but it needs the retrieval surface
   split into named tools and JSON-mode reliability per model.

7. **`.env` is tracked in git** and contains live keys. `.gitignore` exists now
   but does not untrack it: run `git rm --cached .env`.

---

## 10. Running and verifying

```bash
cd legal-rag-ui-workbench

# the UI (needs no API server, no token)
.venv/bin/streamlit run streamlit_app.py --server.port 8504

# the JSON API, if you want it
scripts/up.sh

# data
python -m scripts.ingest data/farsi          # --reset to rebuild
python -m scripts.extract                    # structured entries; uses the LLM
python -m scripts.migrate_fts                # add tsvector columns to an existing DB

# the only quality measurements that exist
python -m scripts.eval                       # retrieval metrics — chunks only
scripts/check.sh                             # endpoint smoke test
```

There is **no unit-test suite**. Verification is `scripts/check.sh` and
`scripts/eval.py`. Python ≤ 3.12 is required (`pgserver`).

### How to guide a change

1. Note the baseline: `python -m scripts.eval`.
2. Change **one** thing — embedding model, chunk size, `top_k`, `RERANK_TOP`,
   the prompt.
3. If embeddings or chunking changed: `python -m scripts.ingest --reset`.
4. Re-run the eval and compare. Keep or revert.

The highest-leverage move remains growing `eval/farsi.jsonl`. Twenty to fifty
questions phrased the way lawyers actually phrase them is worth more than any
model swap — and right now the set does not cover the entry path at all.

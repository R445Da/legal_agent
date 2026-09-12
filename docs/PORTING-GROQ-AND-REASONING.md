# Porting: Groq provider + reasoning preview

> **Status (2026-09-03, branch `streamlit-app`).** Steps 1–4 of §3 have landed,
> plus a Streamlit front end that was not in the original plan.
>
> Done: `LLMResponse.reasoning`; `GroqProvider` (`app/llm/groq_provider.py`)
> registered in the factory; `registry._gateway_models()` generalised to iterate
> `gateways()` with `_looks_non_chat`, a real `User-Agent`, and "trust /models";
> per-model tuning moved into `app/llm/knobs.py` and surfaced as a UI panel that
> re-renders when the model changes; Ollama autostart/pull (§1.5); a static
> reasoning panel (§2.3); `.env` carries `GROQ_API_KEY` / `GROQ_MODEL`.
>
> Not done: **§2.4 streaming SSE** (`/ask/stream`) and §2.5 orchestrator step
> events. Generation is still non-streaming everywhere, so the reasoning panel
> renders collapsed after the fact rather than expanding live.
>
> Verified against Groq on 2026-09-03: 8 chat models discovered, reasoning
> captured on `openai/gpt-oss-20b`, Persian answers grounded in retrieved
> excerpts.

A handoff from the `~/codebases` "Router lab" work (a Streamlit chat bench).
That project added Groq as a first-class backend and a live "thinking" panel
that shows a model's reasoning while it streams. This doc is what you need to do
the same here, in the FastAPI + `app/static/*.html` workbench.

Two parts, independent:

1. **Groq as a gateway** — mostly config + a thin provider subclass.
2. **Reasoning preview** — the workbench's `generate()` is non-streaming today,
   so this is the bigger change: either capture `message.reasoning` from the
   non-streamed response, or add a streaming route.

---

## 0. Moving context between Claude Code sessions

Claude Code sessions are bound to a working directory; a new VS Code window on
this repo gets a fresh session with none of the `~/codebases` context, and there
is no "merge sessions" feature.

- **Transcript copy (full continuity, messy):**
  ```bash
  cp ~/.claude/projects/-home-xeno-codebases/f35c39c7-d8e7-4094-af82-878831962509.jsonl \
     ~/.claude/projects/-home-xeno-Documents-coding-ragflow-legal-rag-ui-workbench/
  ```
  then `claude --resume` in this repo lists it. Every file path and cwd inside
  it still points at `~/codebases`, so the resumed model "remembers" the old
  repo — good for deep continuity, noisy for a clean start.
- **Handoff doc (recommended):** this file. Start a fresh `claude` here and say
  *"read docs/PORTING-GROQ-AND-REASONING.md and ~/codebases/llm/registry.py,
  then implement it in this repo."* Clean context budget, curated signal, you
  review before it acts.

Keep this doc updated as the port lands so the next repo is cheaper again.

---

## 1. Groq as a gateway

### 1.1 The four things that bit us

| # | Symptom | Fix |
|---|---------|-----|
| **Cloudflare 1010** | `GET https://api.groq.com/openai/v1/models` returns `HTTP 403: error code: 1010` from stdlib `urllib` | Send a real `User-Agent` header (any non-default string). The `openai` SDK / `httpx` already send one, so `OpenAIProvider` is fine — but any hand-rolled `urllib`/`http.client` call to Groq needs it. |
| **Token param** | `max_tokens` is deprecated on Groq; reasoning models spend the budget "thinking" and truncate before any answer | Send `max_completion_tokens`, not `max_tokens`, for Groq. |
| **`/models` is authoritative** | A hardcoded default model (`llama-3.3-70b-versatile`) 404'd on send — this key's `/models` does **not** list it | Never assume a model exists. Build the catalog from `/models`; only fall back to a configured default when `/models` returned nothing at all. |
| **Non-chat noise** | Groq's `/models` returns `whisper-*`, `canopylabs/orpheus-*` (TTS), `meta-llama/llama-prompt-guard-2-*` (classifier) alongside chat LLMs | Filter ids containing `whisper`, `tts`, `orpheus`, `prompt-guard`, `-guard-2`, `embed`. |

### 1.2 What this key can actually reach (2026-09)

`gsk_…` free tier → chat models:

```
openai/gpt-oss-120b          openai/gpt-oss-20b       openai/gpt-oss-safeguard-20b
qwen/qwen3.6-27b             qwen/qwen3.8-27b         allam-2-7b
groq/compound               groq/compound-mini
```

No `llama-3.1-8b-instant`, no `llama-3.3-70b-versatile`. Use
`openai/gpt-oss-20b` as the default — fast, free, and it reasons.

### 1.3 Reasoning knobs, per model

| Model class | `reasoning_effort` (`low`/`medium`/`high`) | `reasoning_format: "parsed"` | Where reasoning lands |
|---|---|---|---|
| `openai/gpt-oss-*` | **yes** | no (already split; passing it 400s) | `message.reasoning` / `delta.reasoning` |
| `qwen/qwen3*` | **yes** | yes | `message.reasoning` when parsed |
| other `<think>` reasoners (deepseek-r1 distills, …) | no | **yes** — else `<think>…</think>` is inline in `content` | `message.reasoning` when parsed |
| `llama-*`, `allam-*`, `groq/compound*` | no (400s) | no | n/a |

So: only send `reasoning_effort` to gpt-oss + qwen3; send `reasoning_format:
"parsed"` to non-gpt-oss reasoners; send neither to plain chat models.

### 1.4 How it maps onto this repo

The workbench already has `app/llm/registry.py`, `OpenAIProvider`, and env-driven
config. The port is a **merge**, not a rewrite.

**`app/llm/openai_provider.py` → add a Groq subclass** (it already accepts a
`base_url`, so this is small):

```python
class GroqProvider(OpenAIProvider):
    name = "groq"

    def __init__(self, model: str = "openai/gpt-oss-20b", api_key: str | None = None):
        super().__init__(
            model=model,
            api_key=api_key or os.environ.get("GROQ_API_KEY"),
            base_url="https://api.groq.com/openai/v1",
        )

    async def generate(self, prompt, *, system=None, max_tokens=1024,
                       temperature=0.0, json_mode=False, reasoning_effort=None):
        # Groq: max_completion_tokens, not max_tokens; per-model reasoning knobs.
        lowered = self.model.lower()
        is_gpt_oss = lowered.startswith("openai/gpt-oss")
        extra = {}
        if reasoning_effort and (is_gpt_oss or "qwen3" in lowered):
            extra["reasoning_effort"] = reasoning_effort
        if not is_gpt_oss and ("qwen3" in lowered or "r1" in lowered):
            extra["reasoning_format"] = "parsed"

        client = self._get_client()
        resp = await client.chat.completions.create(
            model=self.model,
            max_completion_tokens=max_tokens,   # <- not max_tokens
            temperature=temperature or 1e-8,    # Groq maps 0 -> 1e-8 anyway
            messages=_msgs(system, prompt),
            **({"response_format": {"type": "json_object"}} if json_mode else {}),
            **extra,
        )
        choice = (resp.choices or [None])[0]
        msg = choice.message if choice else None
        return LLMResponse(
            text=(msg.content if msg else "") or "",
            model=self.model,
            input_tokens=resp.usage.prompt_tokens if resp.usage else None,
            output_tokens=resp.usage.completion_tokens if resp.usage else None,
            raw={**resp.model_dump(), "reasoning": getattr(msg, "reasoning", None)},
        )
```

Add `reasoning: str | None = None` to `LLMResponse` in `app/llm/base.py` and set
it from `getattr(msg, "reasoning", None)` so the pipeline can surface it.

**`app/llm/factory.py`** — register `"groq": GroqProvider` in `_PROVIDERS`.

**`app/llm/registry.py` — generalise `_gateway_models()`.** Today it reads one
gateway from `OPENAI_BASE_URL` / `OPENAI_API_KEY`. Make it iterate a list of
gateways (9router *and* Groq), each `{id, base_url, key, label}`, and for each:

- `GET {base}/models` with `Authorization: Bearer {key}` **and a `User-Agent`
  header** (httpx sends one by default, so `httpx.get(..., headers={...})` is
  fine as long as you don't strip it).
- filter non-chat ids (`_looks_non_chat`, list in 1.1).
- `available = bool(key)` and, on HTTP error, keep the row with
  `available=False` + the reason instead of raising.
- **do not** inject a hardcoded default that `/models` didn't return.

Copy `_looks_non_chat`, `_gateway_model_tuning`, and the "`/models` is
authoritative" logic verbatim from `~/codebases/llm/registry.py`
(lines ~110-140, ~316-406). That file is stdlib-only; the only thing to swap is
`load_profiles()` (reads `st.secrets`) for your env / settings.

**`.env`:**

```
GROQ_API_KEY=gsk_...
# optional: GROQ_MODEL=openai/gpt-oss-20b
```

**`GET /models` route** already returns `registry.catalog()` — once the registry
lists Groq, the header dropdown gets it for free, and any request can carry
`model=groq::openai/gpt-oss-20b`.

### 1.5 Bonus: Ollama autostart

`~/codebases/llm/registry.py` also starts `ollama serve` itself if it is down
(`find_ollama_binary` → `$OLLAMA_BIN`, `~/ollama/bin/ollama`, `PATH`; then poll
`/api/version`). The workbench currently relies on `scripts/serve.sh` doing
this. If you want the API to be able to bring Ollama up on demand (e.g. first
`/ask` after a reboot), port `find_ollama_binary` + `ensure_ollama` +
`list_ollama_models` and call `ensure_ollama()` in `LocalProvider.is_available`
or at app startup.

---

## 2. Reasoning preview

### 2.1 The pattern

A "thinking" panel that:

- **does not exist** until the first reasoning token arrives (no empty box for
  non-reasoning models),
- is **expanded while the model reasons**,
- **collapses** to a "Reasoning" summary the moment the first answer token
  arrives,
- stays in the transcript, collapsed, for replay.

In Streamlit that was `st.status(":shimmer[Thinking]", type="compact")` created
lazily inside a `reasoning_sink(text)` callback, then
`.update(label="Reasoning", state="complete", expanded=False)` after the stream.
See `~/codebases/main.py` lines ~262-300.

### 2.2 Where reasoning comes from

Across providers the field is one of — check all four:

```
choice.message.reasoning
choice.message.reasoning_content
choice.delta.reasoning            # streaming
choice.delta.reasoning_content    # streaming (DeepSeek-style)
```

Anthropic is different again: `thinking` blocks in the content array (needs
`thinking: {type: "enabled", budget_tokens: N}` on the request). Out of scope
for the first pass — Groq gpt-oss covers the demo.

### 2.3 Non-streaming path (smallest change, do this first)

The workbench's `/ask` and `/assistant` return a full JSON body. Just add the
reasoning to it:

- `LLMResponse.reasoning` (added in 1.4) → thread it through
  `RAGAnswer` / the `/assistant` response model as `reasoning: str | None`.
- `app/static/app.html`: when a response has `reasoning`, render a
  `<details class="reasoning">` above the answer bubble:

```html
<details class="reasoning">        <!-- add `open` while awaiting the answer -->
  <summary>Reasoning</summary>
  <div class="reasoning-body"></div>
</details>
```

```css
.reasoning { font-size: .85em; opacity: .8; margin-bottom: .4rem; }
.reasoning[open] .reasoning-body { white-space: pre-wrap; }
```

No live expand/collapse, but you see the chain of thought. Ship this, then:

### 2.4 Streaming path (the real "preview")

Add `POST /ask/stream` (and/or `/assistant/stream`) returning
`StreamingResponse(..., media_type="text/event-stream")`. Emit **typed** SSE so
the client can route reasoning vs answer vs retrieved-doc events:

```
event: sources
data: {"docs": [{"id": 12, "title": "...", "score": 0.71}, ...]}

event: reasoning
data: {"delta": "The question asks about..."}

event: answer
data: {"delta": "Based on the archive, "}

event: done
data: {"input_tokens": 812, "output_tokens": 143}
```

Server side, the RAG pipeline already does `retrieve → prompt → generate`. For
the streaming version:

1. run retrieval, emit one `sources` event (this is your "documents showing in
   the background" — the UI can render citation chips before any text),
2. call the provider in streaming mode (`client.chat.completions.create(...,
   stream=True)`), and for each chunk emit `reasoning` or `answer` deltas from
   the fields in 2.2,
3. emit `done` with the usage totals.

`GroqProvider` needs a `stream_generate()` alongside `generate()` — or lift the
SSE parser from `~/codebases/main.py` `stream_completion()` (lines ~30-110,
stdlib only, handles `data:` framing, `[DONE]`, partial JSON, and all four
reasoning field names).

Client side in `app.html`, an `EventSource` (or `fetch` + `ReadableStream` since
it is a POST):

```js
const res = await fetch("/ask/stream", {method:"POST", headers, body});
const reader = res.body.getReader();
let think = null;                       // the <details> element, created lazily
// ... parse SSE frames ...
//   on "sources":   render citation chips
//   on "reasoning": if (!think) { think = makeDetails(); think.open = true; }
//                   think.body.textContent += delta;
//   on "answer":    if (think) think.open = false;      // collapse on first answer
//                   answerEl.textContent += delta;
//   on "done":      finalize
```

`makeDetails()` inserts the `<details>` from 2.3 into the message bubble.
`think.open = false` on the first `answer` event is the auto-collapse.

### 2.5 Tool calls / orchestrator steps in the background

The workbench's `orchestrator.py` already routes intent (query / archive /
analytics) and does structured extraction. To show that "in the background" like
the reasoning panel, emit more SSE event types from the streaming route —
`event: step` with `{"label": "Classifying intent", "state": "running"}` /
`{"state": "done"}` — and render each as a row in a step list above the answer,
same lazy-create + collapse-when-done treatment. This is the workbench's own
`/bench` grid idea applied to a single request's lifecycle.

---

## 3. Suggested order

1. `LLMResponse.reasoning` + `GroqProvider` + factory registration + `.env`.
2. Generalise `registry._gateway_models()` for multiple gateways; port
   `_looks_non_chat` + `_gateway_model_tuning` + "trust `/models`".
3. Confirm `GET /models` lists Groq and `/ask` with `model=groq::…` works
   (non-streaming, no reasoning yet).
4. Thread `reasoning` into the `/ask` + `/assistant` responses; render the
   static `<details>` panel (2.3).
5. Add `/ask/stream` with typed SSE (2.4); wire the lazy expand/collapse panel.
6. Optional: Ollama autostart (1.5), orchestrator step events (2.5).

## 4. Reference files in `~/codebases`

| File | What to lift |
|---|---|
| `llm/registry.py` | `_looks_non_chat`, `_gateway_model_tuning`, `_get_json` (with the `User-Agent`), `_gateway_entries` "trust `/models`" logic, `find_ollama_binary` / `ensure_ollama` / `list_ollama_models` |
| `main.py` | `stream_completion()` — the stdlib SSE parser handling all four reasoning field names; the lazy `reasoning_sink` + collapse-on-first-content UI logic |
| `.streamlit/secrets.toml` | the working `[router.profiles.groq]` shape |
| `router_lab/README.md` | prose description of the discovery + reasoning behaviour |

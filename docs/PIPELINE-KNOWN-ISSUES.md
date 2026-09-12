# Entry-building pipeline — known issues & rough edges

Status: **the pipeline works end-to-end.** A dictated/typed session goes in and
comes out as an `Entry` with a timeline, scored related records, and labels.

**Update — run modes + speed pass.** The pipeline no longer forces four gates on
every entry. There is a **حالت ثبت مدخل** selector beside the composer:

| mode | stops for you | when to use |
|---|---|---|
| **تأیید یک‌باره** (default) | **once** — a single review panel that only asks about fields that came back empty | the daily case |
| گام‌به‌گام | at every step (extract, timeline, similar, labels) | when you want to correct as you go |
| خودکار | never — extract → derive → commit | trusted / batch input |

And the slow parts are gone from the default path:

- `classify` — **no LLM call** (the router already ran; re-running it here was
  pure latency and a small model would sometimes contradict itself).
- `similar` — one lexical pass instead of a dozen document-frequency queries
  (12 s → ~0 s); the model tool-loop trail is **off** unless
  `SIMILAR_TOOL_BUDGET_S=45`.
- `labels` — **no LLM call** by default (extracted tags + keyword match against
  the taxonomy); `LABELS_LLM=1` turns the model proposal back on.

Measured on `qwen2.5:3b`, CPU: a `تأیید یک‌باره` run is now **~30 s and one
click**, down from ~66 s and four. The only real cost left is `extract` — one
unavoidable LLM call (~25 s on 3b, ~40 s on 7b).

What follows is everything still not clean.

---

## 1. Routing calls a real "new entry" text «نامشخص»

**Symptom.** You paste a لایحه / صورت‌جلسه and the assistant asks *«منظورتان
پرسش از آرشیو است، ثبت مطلب جدید، یا آمار؟»* instead of starting the pipeline.

**Cause.** `ROUTER_MODEL` was `groq::…` (geo-blocked) so routing fell back to the
answer model, and a small local model often reads a genuine `archive` text as
`unclear`.

**Fixed / worked around:**
- `.env` now has `ROUTER_MODEL=local::qwen2.5:7b`. A 7B model routes correctly
  almost always.
- Click **ثبت مطلب** on the clarification — it forces the intent and starts.
- Or set **نوع پیام** to «ثبت مطلب جدید» before sending — skips the router.

The pipeline's own `classify` step never blocks regardless.

---

## 2. Why runs were slow — three separate causes

**a. Groq was geo-blocked, forcing local inference.** Fixed as of 2026-09-06:
`api.groq.com` responds again (keyless request now 401, not 403 — the block
lifted). `.env` is back on `LLM_PROVIDER=groq` / `openai/gpt-oss-20b`.
`extract` on Groq is **~2 s** vs ~25 s local.

**b. The local GPU is only 3.8 GB.** The GTX 1650 fits `qwen2.5:3b` (~1.9 GB)
and nothing bigger — `qwen2.5:7b` and `aya-expanse:8b` spill to CPU and crawl
(~40-60 s). Switching models in the sidebar forces an evict + reload each time.
If you must run local: **stay on `qwen2.5:3b`**, set
`ROUTER_MODEL=local::qwen2.5:3b` too (so routing doesn't load a second model),
and don't touch the model dropdown mid-session.

**c. The embedding model cache was in `/tmp` and got wiped on suspend.**
fastembed defaulted its cache to `/tmp/fastembed_cache`; this machine clears
`/tmp` on sleep/reboot, so `commit` (and search) would then block for minutes
re-downloading a 235 MB ONNX file — and the HF connection kept dropping
mid-transfer. Fixed: `app/rag/embeddings.py` now pins the cache to
`~/.cache/fastembed` and sets `HF_HUB_DISABLE_XET=1` (the Xet backend threw
"CAS Client Error" on this network). **The model still has to finish
downloading once** — if `commit` or a search hangs, the model is still coming
down; let it finish (it resumes across retries) or fetch it on a better
connection and copy `~/.cache/fastembed` over.

`extract`'s `max_tokens=3000` is for full court rulings; it does not slow a
short لایحه (the model stops early).

---

## 3. Labels on a small model

Now keyword-driven by default (no LLM call): extracted `tags` + a match of the
record against the seed taxonomy and the corpus's existing tags, all run through
`taxonomy._clean` (drops procedural words like پرونده/شاکی/متهم and phrases
longer than three words). Short two-word noun phrases can still slip through; the
labels field in the review panel is `st.multiselect` with `accept_new_options`,
so fix them there. `LABELS_LLM=1` re-enables the model proposal (~10-25 s).

---

## 4. The «پرونده‌های مشابه» step casts a wide net

The list is built deterministically from several query facets (topic, case
number, multi-word party names) plus a semantic fallback. On a short archive it
still surfaces loosely-related records — e.g. a generic «برنامه هفتگی دفتر وکالت»
matched a court/office facet.

This is deliberate: the gate has a **نگه‌داری** checkbox per row, so you keep the
two or three that matter and drop the rest before commit. Only the kept rows are
written to `Entry.related`.

The bounded tool loop that runs alongside (the model trying its own search
angles) is **decorative** — its output is shown as a trail but never trusted for
the list, so a fumbled tool call cannot corrupt the results.

---

## 5. Non-standard tool-call formats from local models

`aya-expanse:8b` returns tool calls wrapped as
`{"parameters": {...}, "tool_name": "..."}` instead of the flat arguments other
models (and the OpenAI spec) use. `app/rag/tools.py::_unwrap_args` normalises
this, and identical repeated calls are de-duplicated (small models loop). Other
local models may have their own quirks; add cases to `_unwrap_args` as they turn
up.

---

## 6. The chat transcript is lost when Streamlit restarts

Streamlit session state does not survive a server restart, so the chat messages
(and their link to a run) disappear. **The run itself is safe** — it is in the
`runs` / `run_steps` tables and visible in the build console
(`/runs/view`). But there is currently no "resume this run from the chat" entry
point after a restart; you would drive it from the console's data or start over.

A future fix: on load, re-attach any `awaiting_input` run to a fresh chat card.

---

## 7. `GET /schema` on the API had a drifting copy

`app/main.py::/schema` carried its own hand-written copy of the schema/pipeline
description, separate from `catalog.schema_overview()` (which the Streamlit UI
uses). Both are now updated to the six-step pipeline, but they are still two
copies — change both, or refactor `/schema` to call `schema_overview()`.

---

## 8. The build console SSE polls the database

`GET /runs/{id}/events` streams step changes by polling `run_steps` every 2 s,
not via the in-process pub/sub in `app/rag/runs.py`. This is **by design**: the
Streamlit app and the API server are separate processes, so a run driven from
Streamlit publishes nothing the API process can see. Polling is the reliable
path. The pub/sub only matters if a run is ever driven from inside the API.

---

## 9. Repo hygiene (pre-existing, not caused by this work)

- **`.env` is tracked in git** and holds `GROQ_API_KEY`, `OPENAI_API_KEY`,
  `API_TOKEN`. `.gitignore` documents the fix: `git rm --cached .env`. Until
  then, be careful with `git add -A`.
- Nothing was committed before this — the whole `app/ui/` tree, `streamlit_app.py`
  and most of `app/rag/` were untracked at `8e8e1d9c`. This commit brings them in.
- `CLAUDE.md` lives at the **parent** directory, which is not a git repo, so its
  updates for this feature are on disk only.

---

## 10. Migration

`runs` / `run_steps` auto-create via `create_schema` on next app start.
`Entry.related` is an `ALTER` on the existing table and needs:

```bash
python -m scripts.migrate_runs
```

Idempotent; safe to re-run. It was run once already during the build.

---

## What is solid

- The six-step engine, resumable from any point, every step persisted.
- Deterministic fallback on every LLM-driven step — a model returning junk JSON
  or no tool call never stalls a run.
- Per-step retry (`تلاش دوباره`) re-runs only the failed step; the raw text and
  earlier gates always survive.
- `commit_entry` writes `Entry.related` (scored) **and** `Label` rows, so the
  taxonomy view and tag filters pick up the approved labels.
- Real tool-calling on all four providers; `LocalProvider` only switches to
  Ollama's `/api/chat` when tools are actually passed, leaving the working
  `/api/generate` path untouched.
- The read-only build console at `:8000/runs/view`.

# Running it yourself

A plain operator guide — no AI needed. Everything runs locally on this machine.

Project dir: `~/Documents/coding/ragflow/legal-rag-ui-workbench`
All commands below assume you have `cd`'d into it.

---

## 1. Start the server

```bash
cd ~/Documents/coding/ragflow/legal-rag-ui-workbench
scripts/up.sh
```

That one script, in order: kills any stale server on :8000, starts **Ollama**
(the local model runtime) if it isn't up, pulls the model named in `.env`
(`qwen2.5:3b`) the first time, then runs the **API on port 8000** in the
foreground.

- It **blocks the terminal** while running. `Ctrl-C` stops the API (Ollama keeps
  running).
- To run it in the background instead and get your prompt back:
  ```bash
  setsid scripts/up.sh > ~/rag-server.log 2>&1 & disown
  ```
- First start after a reboot takes ~10–30 s (Ollama boot). Later starts are instant.

---

## 2. Open it in a browser

Go to **<http://localhost:8000/app>**

There are three front-ends on the same server:

| URL | What it is |
|---|---|
| `http://localhost:8000/app` | Persian case-archive console — assistant chat, cases, search, ingest, indexed-docs / retrieval lab |
| `http://localhost:8000/console` | The other case-intelligence UI |
| `http://localhost:8000/` | Developer "lab" — Ask / Search / Eval / Bench, model switcher |

### The access token

Every screen needs a token the first time (the server is token-gated). If a
screen shows "قطع ارتباط" / "اتصال ناموفق", click the **⚙ (gear)** icon and enter:

- **Server URL:** `http://localhost:8000`
- **API token:** `-jmpg9lwa2Ikfo8snUo9CehQ4T1dsR2v`

It's saved in the browser (localStorage) and shared across all three UIs, so you
only do this once per browser. The token is the `API_TOKEN` line in `.env` — if
you change it there, update it in the ⚙ panel too.

---

## 3. Check it's working

```bash
curl -s localhost:8000/health | python3 -m json.tool
```

Healthy output looks like:

```json
{
  "status": "ok",
  "llm_provider": "local",
  "llm_model": "qwen2.5:3b",
  "llm_available": true,
  "indexed_documents": 806,
  "indexed_chunks": 6082
}
```

See what's running:

```bash
ss -tlnp | grep -E ':(8000|11434)'      # 8000 = API, 11434 = Ollama
```

---

## 4. Stop it

- If running in the foreground: `Ctrl-C`.
- If backgrounded:
  ```bash
  pkill -f 'bin/uvicorn app.main'
  ```
- Ollama is left running on purpose (other things may use it). To stop it too:
  `pkill -f 'ollama serve'`.
- The database is an embedded PostgreSQL under `./.pgdata` — it starts and stops
  with the API automatically. Nothing to manage.

---

## 5. Using the app

**Assistant (دستیار):** type a question → grounded answer with `[n]` citations.
Dictate/paste a court-session text → it extracts a structured draft you confirm.
Ask a "how many / which" question → an analytics summary.

**Search (جستجو و پرسش):** "پرسش با پاسخ مستند" = full answer; "فقط جستجوی متن" =
just the retrieved passages with match scores.

**Indexed documents / retrieval lab:** browse all 806 indexed documents, read any
one, and see exactly what the hybrid retriever + reranker return for a query —
with the current retrieval config shown.

**Model picker (top bar):** switch between the local models
(`qwen2.5:3b` / `:7b`, `aya-expanse:8b`) and — if 9router is ever installed —
cloud models. "پیش‌فرض سرور" uses whatever `.env` says. Your pick is remembered.
Local models are slower (~15–50 s per answer) but need no keys and no internet.

---

## 6. Changing the default model

Edit `.env`:

```bash
LLM_PROVIDER=local
LLM_MODEL=qwen2.5:7b      # or qwen2.5:3b (faster) / aya-expanse:8b (better Persian)
```

Then restart (`Ctrl-C`, `scripts/up.sh` again). `up.sh` pulls the model if it's
missing. The UI model-picker overrides this per-request without a restart.

---

## 7. Adding your own documents

Every path below does the **same two things** to each new document:
1. **index** it — chunk → embed → store (so it's searchable), and
2. **extract** it — LLM pulls parties / representation / events / entities / tags
   into a structured case Entry.

Plain text (`.txt`) only — no OCR for PDFs/scans yet.

**One at a time — the UI.** Paste the text into **بایگانی سند جدید**, review the
extracted draft, confirm. Done.

**A folder, once — `scripts/add.py`.**

```bash
.venv/bin/python -m scripts.add path/to/folder          # index + extract every new file
.venv/bin/python -m scripts.add path/to/one-file.txt    # a single file
.venv/bin/python -m scripts.add path/to/folder --no-extract   # index only
```
It skips files already indexed, so re-running is safe. On the local model,
extraction is ~15–40 s per document.

**Automatic — drop files into `data/inbox/`.** Start the watcher in its own
terminal:

```bash
scripts/watch.sh
```
Now anything you drop into `data/inbox/` (from a file manager, `scp`, a cron job,
anything) is indexed + extracted automatically and moved to `data/inbox/done/`.

**Programmatically — `POST /ingest`.** Chunks + embeds immediately, then extracts
in the background (`"extract": true` is the default; set `false` to skip):

```bash
curl -s localhost:8000/ingest -H 'content-type: application/json' \
  -H "authorization: Bearer $API_TOKEN" \
  -d '{"documents":[{"text":"...", "source":"my-doc-1", "title":"..."}]}'
```

**Backfill.** If extraction failed or was skipped for some documents:

```bash
.venv/bin/python -m scripts.extract          # extract every document missing an Entry
```

> The archive already has 806 Iranian court rulings indexed; only ~15 have Entries
> (extraction over all 806 on the local model would take hours). Run
> `scripts/extract` to fill them in, or just add your own documents on top.

---

## 8. Reaching it from another device (optional)

The app is only on `localhost` by default. To get a temporary public HTTPS URL:

```bash
# one time: sign up at https://dashboard.ngrok.com (free), then
ngrok config add-authtoken <your-ngrok-token>

# then, in a second terminal while the server runs:
scripts/tunnel.sh
```

It prints a `https://…ngrok-free.app` URL. Open that, and in the ⚙ panel set the
Server URL to that same URL. The `API_TOKEN` is what keeps it private.

---

## 9. Troubleshooting

| Symptom | Fix |
|---|---|
| Browser shows "اتصال ناموفق" / "قطع ارتباط" | Server not running → `scripts/up.sh`. Or wrong token in ⚙. |
| `/health` says `"llm_available": false` | Ollama down → `~/ollama/bin/ollama serve &`, or `scripts/up.sh` which does it. |
| Answers 500 / "Connection error" | `.env` is set to `combo` but 9router isn't installed. Set `LLM_PROVIDER=local` + `LLM_MODEL=qwen2.5:3b`, restart. |
| Port 8000 already in use | `pkill -f 'bin/uvicorn app.main'` then start again — or `up.sh` clears it for you. |
| First answer very slow | The local model is loading into memory. Subsequent answers are faster. |
| Want to wipe and rebuild the index | `rm -rf .pgdata`, restart, then re-run `scripts/ingest` + `scripts/extract`. |

---

## 10. Tuning retrieval

The retrieval pipeline (all live, all in `.env`): **structure-aware chunking →
Persian text normalization → embeddings (vector search, pgvector) + Postgres
full-text (BM25-role) → RRF fusion → cross-encoder rerank**.

| Want to… | Do this |
|---|---|
| See the live config + per-hit scores | «اسناد نمایه‌شده» → **آزمایشگاه بازیابی** in the UI, or `POST /search` (returns a `config` block) |
| Measure a change | `python -m scripts.eval --collection samples` — add `HYBRID=0` / `RERANK=0` to isolate a stage |
| Search only one body of material | pick a **مجموعه** (collection) in the UI, or `"collection": "samples"` on `/search` and `/ask`. Buckets: `samples`, `rulings`, `cases-en`, `uploads`. `GET /collections` lists them. |
| Re-chunk after editing `chunk_text()` or `textnorm.py` | `python -m scripts.rechunk` (in place, same model — no rebuild) |
| Switch embedding model (e.g. to e5-large, 1024-d) | edit the 3 `EMBEDDING_*` lines in `.env`, stop the server, `python -m scripts.reembed`, restart |
| Add an ANN index (only worth it past ~50k chunks) | `python -m scripts.vector_index` (`--drop` to remove) |
| Change chunk size / structure markers | `CHUNK_TARGET` / `CHUNK_MAX` / `_STRUCT` in `app/rag/ingest.py`, then `scripts.rechunk` |
| Adjust the vector-vs-lexical balance | `RRF_LEX_WEIGHT` in `.env` (0 = vector only, 1 = equal) |

## What's where

```
app/main.py            the API (FastAPI) — all routes
app/static/app.html    the Persian console UI  (/app)
app/rag/               retrieval: retriever.py (hybrid+rerank), embeddings.py, pipeline.py
app/rag/orchestrator.py the assistant router (query / archive / analytics) + prompts
app/llm/               model backends: local (Ollama), openai (9router), anthropic
.env                   all configuration
scripts/up.sh          the start command
data/farsi-courts/     the 806 court-ruling source texts
eval/farsi.jsonl       retrieval test set  ·  scripts/eval.py to score it
```

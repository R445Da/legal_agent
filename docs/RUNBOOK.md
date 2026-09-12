# Runbook — what broke, why, and how to fix it yourself

Everything below actually happened on this machine. Each entry is written so you
can diagnose and fix it without me.

**Start here whenever anything is wrong:**

```bash
cd ~/Documents/coding/ragflow/legal-rag-ui-workbench
scripts/doctor.sh
```

It checks the three servers, tells you whether Groq is blocked *and whether that
is your key or your network*, lists which models are actually usable, and prints
the exact commands to fall back to local.

---

## The four scripts

| command | what it does |
|---|---|
| `scripts/doctor.sh` | diagnose everything. Run this first, always. |
| `scripts/restart-ui.sh` | start/restart UI + console (+ Ollama if down). **Required after editing `.env`.** |
| `scripts/stop.sh [--all]` | stop the UI and console. `--all` also stops Ollama and Postgres. |
| `.venv/bin/python -m scripts.demo` | run a document through the pipeline headless — `--mode auto`, `--model`, `--file`, `--keep`. |

Two rules that caused real errors:

- **Never type `python` or `pip`.** Always `.venv/bin/python`. The system Python
  has none of the dependencies.
- **Never `cd legal-rag-ui-workbench` if you're already in it.** Check with `pwd`.

---

## 1. "Groq is down / my API key is invalid"

**It was never the key.** You replaced it three times; all three worked.

Groq's API sits behind Cloudflare, which blocks **datacenter and VPN IP ranges**.
Your VPN rotates exit nodes, so the same key gets `200` on one node and `403` on
the next. It looks random because it tracks the node, not the clock.

### The one test that settles it

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://api.groq.com/openai/v1/models
```

No auth header at all:

| result | meaning |
|---|---|
| **401** | The endpoint is reachable and evaluating auth. A 403 *with* your key would be real. |
| **403** | The block lands **before** auth. **No key can fix this.** It is the network. |

Observed on this machine — different IPs, different continents, same rejection:

| egress | provider | CF edge | result |
|---|---|---|---|
| 198.44.142.35 | tzulo, inc. | YUL | 403 |
| 167.88.50.50 | Free Range Cloud Hosting | SEA | 403 |
| (residential) | — | AMS / FRA | **200** |

### Fix

**Switch your VPN server** to a residential/consumer exit, or turn the VPN off.
Then `scripts/doctor.sh` until you see `with-key=200`. European exits (AMS, FRA)
have worked; Canadian/US datacenter hosts have not.

Fall back to local while it's blocked:

```bash
sed -i 's|^LLM_PROVIDER=.*|LLM_PROVIDER=local|; s|^LLM_MODEL=.*|LLM_MODEL=qwen2.5:3b|; s|^ROUTER_MODEL=.*|ROUTER_MODEL=local::qwen2.5:7b|' .env && scripts/restart-ui.sh
```

Switch back when it clears:

```bash
sed -i 's|^LLM_PROVIDER=.*|LLM_PROVIDER=groq|; s|^LLM_MODEL=.*|LLM_MODEL=openai/gpt-oss-20b|; s|^ROUTER_MODEL=.*|ROUTER_MODEL=groq::openai/gpt-oss-20b|' .env && scripts/restart-ui.sh
```

### What was fixed in code

- `with_transient_retry` (`app/llm/openai_provider.py`) wraps **every** API call —
  generate and stream, OpenAI and Groq — with 3 attempts and 1/3/6s backoff.
  Short flaps are now invisible. Measured: 12/12 calls succeed, one silently
  recovering from a 403 that used to be a hard HTTP 500.
- After retries are exhausted the error says *"this is the network blocking the
  host, NOT a bad API key (a wrong key returns 401)"* instead of the SDK's
  `PermissionDeniedError`, which is what sent you chasing key rotations.
- `registry._get_json` retries model discovery on 403/429/5xx, so one flap no
  longer marks Groq dead for the whole catalogue cache window.

---

## 2. "It says the model is unavailable (⚠) but the network is fine"

The model panel **caches which models are reachable for 10 minutes**. If you
looked at the app while Groq was blocked, the Groq entries stay marked ⚠ after
the network recovers — and the chat refuses to send to a model marked ⚠.

**Fix (instant, either one):**
- Click **«بازخوانی · اجرای Ollama»** in the left panel — clears the cache, re-checks.
- Or `scripts/restart-ui.sh` — a fresh process starts with an empty cache.

---

## 3. "Everything is slow" (~66s per entry)

Root causes, all fixed:

| step | was | now |
|---|---|---|
| `classify` | a whole LLM call | **no call** — the router already decided upstream |
| `similar` | a dozen document-frequency queries (~12s) | **one** lexical pass (~0.03s) |
| `similar` tool-loop | always ran (10–40s) | **off** unless `SIMILAR_TOOL_BUDGET_S` is set |
| `labels` | an LLM call | **no call** — keyword match against the taxonomy (`LABELS_LLM=1` restores it) |
| gates | 4 mandatory stops | **1** (see run modes below) |

Result: **~66s and 4 clicks → ~5s and 1 click** on Groq; ~24s on local.

The only unavoidable cost is `extract` — one model pass. Measured: **1.5s** on
Groq vs **60s** on `qwen2.5:3b`. That 40× is the whole argument for using a
cloud model when the network allows it.

### Run modes — «حالت ثبت مدخل» beside the composer

| mode | stops for you | use when |
|---|---|---|
| **تأیید یک‌باره** (default) | **once**, at a review panel that only asks about fields that came back empty | daily use |
| گام‌به‌گام | at every step | you want to correct as you go |
| خودکار | never — extract → derive → commit | trusted/batch input |

---

## 4. "Ollama returns 500 on every request"

Symptom: `500 Internal Server Error` from `localhost:11434/api/generate`, with
`llama-server binary not found` in the body. `/api/tags` still works, so the
model list looks healthy.

**Cause:** two Ollama installs. `/usr/local/bin/ollama` is broken — its runtime
directory has no `llama-server` and no `libggml*`. `~/ollama/bin/ollama` is
complete. A stale daemon from the broken one answers HTTP but cannot infer.

**Check which one is running:**

```bash
ls -l /proc/$(pgrep -f 'ollama serve')/exe
```

**Fix — do not reinstall, just restart from the good binary:**

```bash
pkill -f 'ollama serve'
nohup ~/ollama/bin/ollama serve > ~/ollama-serve.log 2>&1 &
```

`scripts/restart-ui.sh` now does this automatically when :11434 is silent, and
prefers `~/ollama/bin/ollama`.

---

## 5. "The app hangs for minutes on the first search"

The embedding model cache lived in `/tmp/fastembed_cache`, which the system
wipes. Losing it made every embed call block on a ~235 MB re-download — and the
download itself failed with `CAS Client Error` from HuggingFace's Xet backend.

**Fixed in `app/rag/embeddings.py`:** the cache is now `~/.cache/fastembed`
(persistent), and `HF_HUB_DISABLE_XET=1` forces plain HTTPS.

---

## 6. Claude (Anthropic) — added, but the account has no credits

Claude is now a first-class provider: 11 models discovered live from
`/v1/models`, including Opus 5, Sonnet 5 and Fable 5.

**Current blocker:** the key is valid (`/v1/models` → 200) but

```
POST /v1/messages → 400 "Your credit balance is too low"
```

Confirmed not a code problem — a minimal raw `curl` gets the same error. Add
credits at **console.anthropic.com → Plans & Billing** and it works immediately;
no restart needed.

Three bugs in the old provider that would have 400'd on every current model:

1. `json_mode` used an **assistant prefill** — rejected on Opus 5 / Sonnet 5 / 4.6+.
2. It sent **`temperature`** unconditionally — removed on Opus 5 / Sonnet 5 / 4.7–4.8.
3. **No thinking, no streaming.**

Make Claude the default once it has credits:

```bash
sed -i 's|^LLM_PROVIDER=.*|LLM_PROVIDER=anthropic|; s|^LLM_MODEL=.*|LLM_MODEL=claude-opus-5|; s|^ROUTER_MODEL=.*|ROUTER_MODEL=anthropic::claude-haiku-4-5|' .env && scripts/restart-ui.sh
```

---

## 6b. "The model answered with nothing"

Empty bubble, no error — or `400 json_validate_failed`. On a reasoning model the
token budget pays for hidden thinking *first*, so a small cap is spent before the
answer starts. Raise **«سقف توکن خروجی»**, then lower **«میزان استدلال»**.

Full explanation, with the measured reproduction: **`docs/GROQ-TOKEN-BUDGET.md`**.

---

## 6c. Embedding model changed → search silently returns nonsense

The one failure here that produced *wrong answers* rather than an error. Two
different 384-dim models both fit `Vector(384)` and both insert cleanly, but
their coordinate spaces are unrelated, so a query vector from model A compared
against chunks from model B is noise — and the LLM summarises that noise
confidently.

**Now guarded.** `create_schema()` records which model wrote the vectors and
refuses to start on a mismatch:

```
Embedding model changed, but the stored vectors were not rebuilt.
  vectors in the database were written by : ...MiniLM-L12-v2|dim=384|prefixes=0
  the current configuration is            : BAAI/bge-small-en-v1.5|dim=384|prefixes=0
  (7482 chunks affected)
```

If you meant to change it, rebuild:

```bash
.venv/bin/python -m scripts.ingest --reset && .venv/bin/python -m scripts.extract --reset
```

---

## 7. Smaller things worth knowing

- **Enter may not submit** in the chat box — click the **send arrow** instead.
- **Routing calls a real filing «نامشخص»** on a small model. Either pin
  `ROUTER_MODEL` to a 7B+ model, click **«ثبت مطلب»** on the clarification, or
  set **نوع پیام** to «ثبت مطلب جدید» before sending.
- **Labels are noisy on small models.** Procedural words (پرونده، شاکی، دفاعیه…)
  are stripped by `taxonomy._clean`; fix the rest in the review panel.
- **`.env` is tracked in git** and holds your keys. `git rm --cached .env` stops
  that — and rotate the keys, since they're already in history.
- **Chat transcript is lost on restart.** The *runs* survive in the database and
  the console (`:8000/runs/view`); only the chat bubbles go.

---

## Health check, end to end

```bash
scripts/doctor.sh                                  # all green?
.venv/bin/python -m scripts.demo --mode auto       # pipeline works?
```

Then open **http://localhost:8501** → **۰۱ دستیار پرونده** → paste a document.

Console with every run's steps and timings:
`http://localhost:8000/runs/view?token=$(grep ^API_TOKEN= .env | cut -d= -f2)`

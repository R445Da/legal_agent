# Deploying — sizes, options, and the one gotcha

## What actually moves

| | size | who pays the bandwidth |
|---|---|---|
| **Your upload: source** | **~16 MB** | you |
| Your upload: `seed.dump` (existing archive) | 15 MB | you, once |
| `data/` corpus | 468 MB | **skip it** — `seed.dump` already holds the archive |
| Base image + pip packages | ~700 MB | the build server |
| Embedding + reranker models | ~1.4 GB | the build server |
| Ollama models (optional) | 11 GB | the server, only if you run local models |

**You upload ~30 MB.** Everything heavy is pulled by the machine doing the
build, over its datacenter link.

**Do not push your local image.** `legal-rag:latest` is 3.62 GB and x86-64 —
it will not run on Oracle's ARM instances, and pushing it from home is slow.
Build on the server from 16 MB of source instead.

---

## The gotcha, before you choose anything

**Every cloud host has a datacenter IP, and Groq's edge blocks those.** We
measured it repeatedly: `403` arrives *before* authentication, so no key fixes
it, and unlike a VPN you cannot rotate a datacenter's exit node.

So a deployed instance must use one of:

- **Anthropic** — works from datacenter IPs (verified). Needs credits.
- **Ollama on the same box** — free, no network dependency, but CPU-only.

This matters most for the **accounting agent**, which currently calls Groq for
both the model and Whisper STT (`backend/orchestrator/llm_client.py`,
`backend/routers/voice.py`, `backend/core/config.py`). Deploying it unchanged
means it cannot reach its model. It already ships `faster-whisper` as an offline
STT fallback, so the voice half can go local; the LLM half needs a decision.

---

## Option A — Oracle Cloud Always Free (the permanent home)

**4 ARM cores · 24 GB RAM · 200 GB disk · free forever.** More RAM than the
laptop this was built on, which is why it is the only free tier where **Ollama
actually runs** — so you can have no API bill and no Groq problem at all.

Two caveats:

- **ARM64.** `pgserver` publishes no linux-aarch64 wheel, which is why
  `Dockerfile.cloud` drops it and requires a managed `DATABASE_URL`.
- **Capacity.** Free A1 instances are heavily oversubscribed; `Out of capacity`
  on provisioning is common and can take days of retrying. Nothing technical,
  just be ready for it.

```bash
# on your machine — 16 MB
rsync -az --exclude .venv --exclude .pgdata --exclude data --exclude __pycache__ \
      ./ ubuntu@<oracle-ip>:~/legal-rag/

# on the server
cd ~/legal-rag
docker build -f docker/Dockerfile.cloud -t legal-rag:cloud .
docker run -d --name legal-rag -p 80:8501 --env-file .env.cloud legal-rag:cloud
```

### Editing code on the server

Yes — three ways, in order of comfort:

1. **VS Code Remote-SSH** (best). Install the *Remote - SSH* extension, connect
   to `ubuntu@<ip>`, and the whole project opens as a normal workspace with a
   terminal. Edit, then `docker build` again.
2. **Keep editing locally**, `rsync` the 16 MB up, rebuild. Fast enough.
3. `ssh` + `vim`/`nano` for one-line fixes.

For a tight loop, bind-mount the source instead of rebuilding:
`docker run -v ~/legal-rag/app:/app/app …` — Streamlit reloads on save.

---

## Option B — Hugging Face Spaces (live in ~5 minutes)

x86, no capacity queue, free. Good for showing someone today; weaker as a
permanent home because free Spaces sleep when idle and have no durable disk —
which is fine here, since the database is external anyway.

```bash
# create the Space first at https://huggingface.co/new-space  (SDK: Docker)
deploy/to-huggingface.sh <your-username>/<space-name>
```

The script pushes source only. HF builds the image on their machines, pulling
the models from HF's own CDN — that is the answer to "without downloading all
that data": you never do.

Then set in **Settings → Variables and secrets**: `DATABASE_URL`,
`ANTHROPIC_API_KEY`, `LLM_PROVIDER=anthropic`, `LLM_MODEL=claude-opus-5`,
`PORT=7860`.

---

## The database, either way

Free Postgres with pgvector — **Supabase** or **Neon**. Both work; Supabase's
free tier caps at 500 MB and yours is 154 MB today.

```bash
# move the existing archive up
pg_dump "$(grep ^DATABASE_URL .env | cut -d= -f2)" | psql "<supabase-url>"
# or restore the packaged seed
psql "<supabase-url>" < docker/seed.dump
```

Then set `DATABASE_URL` in the deployment. `resolve_database_url()` bypasses
`pgserver` entirely when it sees a real URL, which is what makes the ARM image
possible.

---

## Fastest to something live

| | time | permanent? |
|---|---|---|
| Cloudflare tunnel (`scripts/tunnel.sh`) | 30 seconds | no — your laptop serves it |
| Hugging Face Spaces | ~5 min | sleeps when idle |
| Oracle Cloud | ~10 min of work + provisioning wait | yes |

---

## Option C — GitHub Codespaces (practice ground)

The place to learn this before committing to Oracle: a free cloud machine
(60 h/month on a personal account) that builds the dev container, runs the app,
and gives you a shareable preview URL — all in the browser.

```
push to GitHub  →  Code ▸ Codespaces ▸ Create
```

`.devcontainer/` does the rest: a Python container, a real **pgvector** Postgres
beside it, the venv built, the schema created and the seed archive loaded. Port
8501 forwards automatically and VS Code opens a preview; the **Ports** tab has a
*Visibility → Public* switch that gives you a URL to send someone.

Set the model key once, as a Codespaces secret, not in a file:
`github.com/settings/codespaces` → **New secret** → `ANTHROPIC_API_KEY`.

Note that a Codespace runs on Azure — a datacenter IP — so **Groq is blocked
there too**. `.devcontainer/setup.sh` writes an Anthropic `.env` when that
secret exists and otherwise the offline `mock` model, so every screen works
either way. It restores `docker/seed.dump` with `pg_restore` (a PG 16 custom
archive — `psql` cannot load it), runs the migrations, and seeds the insurance
edition on top. Re-running the script is safe.

### What CI does on every push

A `test` job first runs the app against a real **pgvector** container — the
insurance seed, every API endpoint (`scripts/check.sh`), every UI section
(`scripts/ui_smoke.py`), and a restore of `docker/seed.dump` plus migrations —
on the offline mock model, so it needs no secret.

Then `.github/workflows/docker.yml` builds `Dockerfile.cloud` for **linux/amd64 and
linux/arm64** and publishes to `ghcr.io/<you>/<repo>`. That is the same image
Oracle (ARM) and HF Spaces (x86) pull — one build, both targets. A pull request
builds x86 only, because an emulated ARM build takes ~20 minutes and a PR does
not need a publishable artifact.

Then a `smoke` job asserts the one thing worth asserting: the image **refuses to
start without a DATABASE_URL** rather than coming up broken.

Deploy the image CI already built:

```bash
docker run -d -p 80:8501 \
  -e DATABASE_URL='postgresql://…' \
  -e LLM_PROVIDER=anthropic -e LLM_MODEL=claude-opus-5 \
  -e ANTHROPIC_API_KEY='sk-ant-…' \
  ghcr.io/<you>/<repo>:latest
```

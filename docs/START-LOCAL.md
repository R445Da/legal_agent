# Starting the legal agent locally

Everything runs from the project folder in WSL. There is no Docker in this
distro, so use the scripts below, not `docker compose`.

One engine, three ways in — all on the same archive:

| what | URL | started by |
|---|---|---|
| **Streamlit UI** (the primary Persian UI, 20 sections) | http://localhost:3012 | `scripts/restart-ui.sh` |
| **API console** (FastAPI, `/docs` for every endpoint) | http://localhost:8000 | `scripts/restart-ui.sh` |
| **React UI «بیمه ایران حقوقی»** (built) | http://localhost:8000/legal/ | the API above, once the app is built (§ 1.3) |
| React UI, live dev server (only while editing it) | http://localhost:5173 | `scripts/legal-web.sh` (§ 3) |

Both UIs share the conversation list: a chat started in one opens in the
other (the «گفتگوها» button in React; in Streamlit, «گفتگوها» above the chat once one is open).

## 0. Which folder has the latest code

The current work is on the branch **`claude/legal-web-with-editing`** (the
React app + conversations + editing an entry by proposal). Check what your
folder is on:

```bash
cd /home/amirswli/legal_agent
git branch --show-current          # want: claude/legal-web-with-editing
```

If it says something else, § 5 moves the folder onto it.

## 1. One-time setup (per folder, and again after pulling new code)

```bash
cd /home/amirswli/legal_agent

# 1.1 Python packages — always the venv binaries, never plain `python`
uv pip install -r requirements.txt -r requirements-dev.txt

# 1.2 Database migrations for the archive in .pgdata-v2 (safe to re-run)
.venv/bin/python -m scripts.migrate_conversations

# 1.3 Build the React UI (Node 20.19+; `npm install` only the first time)
cd iran-insurance-legal && npm install && npm run build && cd ..
```

1.2 is required for this branch: it adds the chat tables and the
`assistant_answers.conversation_id` column. Starting the app creates missing
*tables* on its own but never adds a column to an existing one. (It has
already been run once on `.pgdata-v2`; running it again changes nothing.)

## 2. Start (the normal case)

```bash
cd /home/amirswli/legal_agent
UI_PORT=3012 scripts/restart-ui.sh
```

That one script:

1. stops any old UI / API processes
2. starts the **API console** on http://localhost:8000 (log: `api.log`) — which
   also serves the **React UI** at http://localhost:8000/legal/ if § 1.3 was built
3. starts the **Streamlit UI** on http://localhost:3012 (log: `ui.log`)
4. prints the active model from `.env`

Drop `UI_PORT=3012` to get the default port 8501. Pick the model in the left
panel (Streamlit) or in «تنظیمات» (React). The first start after a reboot takes
a little longer because the embedded Postgres in `.pgdata-v2` has to boot.

The script also tries to start Ollama for local models. On this machine the
Ollama binary is not installed, so it prints
`Ollama -> binary not found; local models will be unavailable`. That is fine
as long as `.env` says `LLM_PROVIDER=groq` (it does).

**Always start from the project folder.** `.env` says `PG_DATA_DIR=.pgdata-v2`,
a path relative to where you start. Started from anywhere else, the app
quietly opens (or creates) a different, empty database.

## 3. The React UI while you are editing it

Only needed if you change files under `iran-insurance-legal/src/` and want them
to reload live. The built app of § 2 is enough to *use* it.

```bash
# beside a running restart-ui.sh stack: its own API on 8010, live UI on 5173
API_PORT=8010 scripts/legal-web.sh

# fully offline — mock model, no keys, a separate seeded archive in .pgdata-legal-web
scripts/legal-web.sh --offline
```

`legal-web.sh` refuses to start if its API port is already taken — hence
`API_PORT=8010` next to § 2's API on 8000. Ctrl-C stops what it started. After
editing the React code, `npm run build` again so http://localhost:8000/legal/
shows the change.

The offline mode never touches `.pgdata-v2`. Its mock model answers, routes and
files entries, but it never proposes an edit; the edit confirmation card only
appears with a real model (the agent — «پژوهش عاملی» — proposes the change,
you confirm it).

## 4. Check that it is up

```bash
UI_PORT=3012 scripts/doctor.sh
```

This checks the servers, tests whether Groq is reachable from your current
network, and lists which models are usable. Quick manual version:

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8000/health          # want 200
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:3012/_stcore/health  # want 200
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8000/legal/          # want 200 (React built)
```

`/health` also shows the model and whether it is available
(`"llm_available": true`) and how many documents are indexed.

## 5. Moving the main folder onto the latest branch (once)

The branch may be checked out in a Claude Code worktree under
`.claude/worktrees/`; git allows a branch in one folder at a time, so free it
there first. Then two local files in the main folder would block the switch:
`.claude/launch.json` (its `streamlit-wsl` / `api-wsl` entries are already in
the branch) and an untracked `docs/START-LOCAL.md` (this file replaces it).

```bash
cd /home/amirswli/legal_agent
git -C .claude/worktrees/atlas-ai-accounting-app-e009bc switch --detach   # only if that worktree exists
git checkout -- .claude/launch.json
mv docs/START-LOCAL.md ~/START-LOCAL.old.md
git fetch origin
git switch claude/legal-web-with-editing
```

Then do § 1 (packages, migration, React build) and § 2.

## 6. Stop

```bash
scripts/stop.sh          # UI + API; leaves Postgres running
scripts/stop.sh --all    # also stops Postgres and Ollama
```

`legal-web.sh` (§ 3) stops with Ctrl-C in its own terminal.

## 7. Restart after changing `.env` or pulling new code

A running process keeps the `.env` and the code it started with.

- after editing `.env` (a key, a model): `UI_PORT=3012 scripts/restart-ui.sh`
- after `git pull`: § 1 (it is safe to re-run all of it), then the restart above

## 8. When something is wrong

| symptom | what to do |
|---|---|
| UI page does not load | `tail -30 ui.log`, then restart with § 2 |
| API `/health` is not 200 | `tail -30 api.log`. Usually the port is held by an old process: `scripts/stop.sh` then restart |
| http://localhost:8000/legal/ is 404 | the React app is not built: § 1.3, then restart the API (§ 2) |
| React says «اتصال به سرور برقرار نشد» | the API is not running, or React points elsewhere: «تنظیمات › اتصال» |
| an error ending in `conversation_id does not exist` in `api.log` / `ui.log` | the migration was skipped: `.venv/bin/python -m scripts.migrate_conversations`, then restart |
| the archive looks empty or the counts are wrong | started from the wrong folder (§ 2, last paragraph) — `/health` shows `indexed_documents` |
| `legal-web.sh`: `something is already serving :8000` | use `API_PORT=8010 scripts/legal-web.sh`, or `scripts/stop.sh` first |
| Model shows ⚠ in the left panel | click «بازخوانی · اجرای Ollama» in the UI, or restart |
| Groq errors / 403 | run `scripts/doctor.sh`. A keyless `403` means your VPN exit node is blocked, not the key. Switch VPN server or turn it off. Details in `docs/RUNBOOK.md` section 1 |
| `ModuleNotFoundError` (e.g. `google.genai`) | § 1.1 — `requirements.txt` gained a package since the venv was built |
| `python: command not found` or import errors | always use `.venv/bin/python`, never plain `python` |

## 9. Running from a Claude Code worktree

A worktree under `.claude/worktrees/<name>/` has the code but no `.venv` and
no archive of its own (`.env` is still found — the app looks for it in the
parent folders). Point both at the main folder, from inside the worktree:

```bash
V=/home/amirswli/legal_agent/.venv/bin
export PG_DATA_DIR=/home/amirswli/legal_agent/.pgdata-v2     # absolute, or it opens an empty one
(cd iran-insurance-legal && npm install && npm run build)
nohup $V/uvicorn app.main:app --host 127.0.0.1 --port 8000 > api.log 2>&1 &
nohup $V/streamlit run streamlit_app.py --server.port 3012 --server.headless true > ui.log 2>&1 &
```

`scripts/restart-ui.sh` does not work there (it expects `.venv/` in the
folder); `scripts/stop.sh` does.

## 10. Other ways to run (only if you need them)

- **API only, in the foreground**, on 0.0.0.0:8000 with the legacy web UI at
  `/app`: `scripts/up.sh` (Ctrl-C stops it).
- **Headless demo** of one document through the pipeline:
  `.venv/bin/python -m scripts.demo --mode auto`.
- **From the Claude Code launch menu**: `.claude/launch.json` has `streamlit`
  (port 8502), `streamlit-wsl` and `api-wsl` (8502 / 8000, from Windows), and
  `iran-insurance-legal (React, offline)` (5180).

Full troubleshooting history lives in `docs/RUNBOOK.md`.

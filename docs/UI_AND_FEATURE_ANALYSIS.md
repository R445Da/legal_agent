# UI, Prompt & Feature Analysis — decision brief

Written 2026-08-28. Purpose: give you (and stakeholders) a clear picture of
**what exists**, **what the modification request is asking for**, **how far
apart those are**, and **what to actually build first** — including what should
run in the background. Analysis only; no code was changed. Other agents are
actively editing core files (see §7).

---

## 1. The three artifacts on the table

| # | File | What it is | Maturity |
|---|---|---|---|
| A | `context_modification.md` | The **vision / system-prompt spec**: a maximal "Legal Case Intelligence Agent" — Case Vault, knowledge graph, OCR pipeline, workflow + reminder engines, permission-aware retrieval, confidence policy, agentic multi-hop RAG, work-product generation, audit + versioning. | Aspirational. 12–18 month product, not a feature sprint. |
| B | `legal-archive-prototype.html` | A **UI mockup** visualizing a *slice* of the vision: sidebar IA (dashboard / cases / events / ingest / search / analytics), a case-detail "folder" with tabs, an animated ingest pipeline, confidence "stamps", a human-review queue. | 100% hardcoded data, zero API calls. A design language + IA proposal. |
| C | `app/` (running build) | The **working MVP**: `Document` / `Chunk` / `Entry` tables, single-shot intent router, vector-only retrieval, one-textarea assistant + Ask / Search / Eval / Library dev tabs. A second team is adding multi-model benchmarking. | Real, wired, deployed behind an ngrok tunnel. |

### The gap that matters most

The prototype (B) is organized around a **Case** entity. The backend (C) **has
no Case entity.** It has:

- `Document` — one raw text blob + its chunks/embeddings
- `Entry` — the structured extraction of *one* session/note (parties,
  representation, events, entities, tags), optionally linked to one Document

There is **no aggregate** that groups many documents + entries under one case
number with a status, procedural stage, priority, financial rollup, aggregated
timeline, or outcome. **Almost every screen in the prototype needs that
object.** So the prototype is not a re-skin of the current UI — it implies a
schema addition (a `Case` table + links). Plan accordingly.

---

## 2. UI check-up — current build (`app/static/index.html`)

**Aesthetic:** clean developer tool. Terracotta accent, system font,
dark-mode-aware, single 860px column, tab bar. Honest and functional.

**Strengths (keep these):**
- Genuinely wired to the API; real loading / error / health / token states.
- RTL handled per-field (`dir="rtl"` / `dir="auto"`), not globally — correct for
  mixed Farsi/Latin content.
- Citation UX: `[n]` in the answer links to the source card and flashes it.
- Keyboard shortcuts, self-contained (no build step, no dependencies).

**Weaknesses vs. a product:**
- No case/entity navigation — everything is a flat text box → result.
- "Library" dumps documents + entries + stats into one long scroll.
- Mixed-language chrome: Persian tabs (`دستیار`) next to English (`Ask`,
  `Search`, `Eval`, `Library`). Inconsistent for an all-Farsi audience.
- Mic button is a disabled stub.
- The extract → confirm → commit flow isn't shown as a pipeline; the draft just
  appears.
- `Eval` tab + model switcher are **internal tooling leaking onto the
  end-user surface** (they belong in a separate "lab"/admin view).

## 3. UI check-up — prototype (`legal-archive-prototype.html`)

**Aesthetic:** strong, distinctive, appropriate. A "case file / ledger"
metaphor: mono digit-boxes for case numbers, dashed "court-stamp" status
badges, muted-paper palette, IBM Plex Mono for numbers, Vazirmatn for Persian.
It reads as *a legal records system*, not *a chatbot*. Full RTL, proper sidebar
IA. **This is the right direction.**

**Good product instincts already baked in (and they match spec A):**
- Case-centric nav + a case "cover + folder tabs" detail view.
- Confidence shown as a visible stamp; an explicit **"needs human review" queue**
  on the dashboard (spec §28).
- Ingestion shown as a **visible multi-stage pipeline** with a match-confidence
  result (spec §5).
- "Similar cases" with a match-% bar **and a disclaimer that similarity ≠
  outcome prediction** (spec §15).
- Analytics framed as descriptive, not predictive (spec §16).

**What it hides / hand-waves (the work behind the screens):**
- All data is fake; there are no loading / empty / error states.
- The pipeline animation is `setTimeout`, not real work.
- Financial, outcome, priority, procedural stage, confidence — invented fields
  with **no extractor behind them**.
- "Similar cases" match % is hardcoded; no backend.
- Global search is a client-side `.includes()` over 6 objects.
- No auth, no settings panel, no multi-user / permissions (spec §29 wants
  permission-aware retrieval).

## 4. Design verdict

**Adopt the prototype's design language and information architecture** — they're
good and they match the spec's intent. But treat the prototype as the
**target skin**, and migrate in stages:

- Keep the current UI's **engineering** (API wiring, RTL handling, citation UX,
  state handling).
- Adopt the prototype's **shell** (sidebar, Case Vault, stamps, pipeline view).
- Build it as a **new static file / `web/` dir**, not by rewriting
  `index.html` in place (another agent is editing that file right now — §7).
- Move `Eval` + model switcher into a separate admin/lab view.
- Pick one chrome language: **all Persian** for the end-user app.

---

## 5. Prompts — what's there, what to change

All prompts live in `app/rag/orchestrator.py` (which another agent is editing —
propose, don't merge).

| Prompt | State | Gap vs. spec A |
|---|---|---|
| `_INTENT_SYSTEM` (router) | Good few-shot, Persian examples. **Only 3 classes: query / archive / analytics.** | Spec §21 wants: "find similar cases", "cases with a hearing next month", "cases with claim > X", "این پرونده چی شد؟" (status of *a specific* case). Today these all fall into `query` and get answered by generic vector RAG — which the README itself admits fails on relational/filter questions. |
| `_EXTRACT_SYSTEM` | Solid schema: parties / representation / events / entities / tags. | No case **status**, **procedural stage**, **financial** fields (claimed / awarded / fee / currency — spec §20), no **confidence**, no **`requires_human_review`** (spec §5/§28/§36), no page / source-span for traceability (spec §14). |
| `pipeline.SYSTEM_PROMPT` | "Answer only from excerpts, cite `[n]`, match the question's language." | Fine as-is. |
| analytics summary prompt | Concise, language-matched. | Fine for its scope. |

**Recommended prompt work (in priority order):**
1. **Add `requires_human_review` + `confidence` to `_EXTRACT_SYSTEM` output.**
   Cheap, high value, and the prototype already has the UI for it.
2. **Expand the router taxonomy** — add `case_lookup`, `similar_cases`,
   `events`/`deadlines`, `filtered_search`. *Or* add a second-stage
   slot-filling prompt that pulls filters (case number, date range, amount,
   court, outcome) out of the message.
3. **Add financial + status fields** to the extraction schema.
4. Keep everything in JSON mode with the existing `_parse_json` fallback.

---

## 6. Use cases — priority ranking for *this* codebase

**Tier 1 — achievable on the current stack, high value:**
- ✅ Q&A over the archive with citations *(done)*
- ✅ Dictate/type a session → structured draft → confirm → archive *(done)*
- ✅ Corpus analytics: counts, top lawyers / topics / people *(done)*
- ⬜ **Similar-case retrieval** — vector index already supports it; needs a UI
  surface + a prompt ("given this case, here are N similar past cases, why,
  their outcome, + disclaimer"). (spec §15)
- ⬜ **Deadline / event list** — `Entry.events` is already extracted; needs an
  endpoint that flattens events across entries, sorts by date, filters
  upcoming. **No LLM needed.** (spec §17–19)
- ⬜ **"Needs human review" queue** — add the confidence + flag to extraction,
  render the queue. (spec §28)

**Tier 2 — needs the `Case` entity, but no new ML:**
- Case Vault view (group documents + entries by case number). (spec §4/§8)
- Aggregated case timeline. (spec §17)
- **Case matching on ingest** — "this document looks like case ۱۴۰۲…۱۱, confirm?"
  from case_number + parties + court + vector similarity, with a confidence
  band. (spec §7)
- **Duplicate detection** on ingest (hash + source + semantic). (spec §33)
- Financial rollup per case. (spec §20)

**Tier 3 — genuine R&D, out of scope for a feature sprint:**
- OCR / document understanding for PDFs & scans (ingestion is plain-text only
  today). (spec §5–6)
- Knowledge graph + relationship-aware retrieval. (spec §10)
- Agentic **multi-hop** RAG with a retrieval-sufficiency loop — today's "agent"
  is single-shot. (spec §11–13)
- Workflow engine + reminder engine + notifications. (spec §19/§22–23)
- Permission-aware retrieval, multi-user, audit, versioning. (spec §29–31/§44)
- Work-product generation (reports, drafts, checklists). (spec §24–25)
- External legal-source research. (spec §38)

---

## 7. What runs in the background — the "simultaneously" question

**Today: nothing.** Everything is synchronous inside the HTTP request.
`/assistant` on archive intent does classify (LLM) + extract (LLM) + vector
search, all blocking, 10–40s. `scripts/extract.py` is a manual batch job. Spec
§5 explicitly says ingestion should **not** finalize immediately — it's a
multi-stage pipeline.

**What belongs in a job queue** (a simple one is fine — an `asyncio` background
task, or `arq`/`rq` on the Postgres that's already running):

| Job | Trigger | Why it can't stay inline |
|---|---|---|
| **Ingest pipeline** (validate → [OCR] → classify → extract entities → case-match → dedupe → event/financial extract → embed → index → update case) | document upload | multi-minute; the prototype already draws it as steps |
| **Structured extraction** (`extract_entry`) | after a Document is created | ~15s/doc LLM call; shouldn't block upload |
| **Similar-case precompute** | after an entry is committed/updated | makes the "similar" tab instant instead of a live vector query per open |
| **Case matching + confidence** | new document | compares against every case |
| **Duplicate detection** | new document | hash + semantic compare |
| **Deadline scan → reminder creation** | nightly + after each extraction | spec §19: the LLM extracts events, a **scheduler** owns the clock |
| **Contradiction / conflicting-date detection** | after extraction, across a case | spec §32 |
| **Entity resolution / name normalization** | nightly | so `/stats` stops double-counting `آقای رضا کریمی` vs `رضا کریمی` |
| **Eval / benchmark runs** | on model or prompt change | spec §45–46; the other team's `/eval` is the seed |
| **Audit-log writes** | every mutation | spec §44 |
| **Re-embed / re-index** | on `EMBEDDING_MODEL` change | full corpus pass |

**Minimum viable version:** one background worker that, on `POST /ingest` or
`/assistant/commit`, enqueues *(extract → case-match → dedupe →
similar-precompute → event-scan)* and writes progress to a `jobs` table the UI
polls. That single change unlocks the prototype's pipeline screen, the review
queue, and instant similar-case / timeline views.

---

## 8. Coordination — do NOT touch these (other agents are in them)

Recently modified by other agents; editing these will collide:

- `app/llm/registry.py` *(new)*, `app/llm/*_provider.py` — model catalog /
  benchmarking layer
- `app/rag/evaluate.py` *(new)*, `scripts/eval.py` — eval harness
- `app/main.py` — `/models`, `/eval`, per-request `_llm(model)` override,
  `EvalRequest`
- `app/rag/orchestrator.py`, `app/rag/pipeline.py` — actively changing
- `app/static/index.html` — model switcher + Eval tab were just added here
- `docs/pipeline-playbook.html` — another agent's doc

**Safe for a UI / feature workstream to own without collision:**
- A **new** static file (`app/static/app.html` or a `web/` dir) for the
  Case-Vault UI — don't edit `index.html` in place
- **New** DB models in a **new** file (`app/db/case.py`) — a `Case` table + link
  tables; additive, no change to `Document` / `Chunk` / `Entry`
- **New** endpoints in a **new** router file (`app/routers/cases.py`), wired
  with one `app.include_router(...)` line in `main.py`
- A **new** `app/jobs/` module for the background worker
- Prompt changes written as a **proposal doc** for the `orchestrator.py` owner
  to merge

---

## 9. Recommended sequence (if you want one)

1. **Prompts (proposal):** add `confidence` + `requires_human_review` to the
   extraction schema. Hand to the orchestrator owner.
2. **Schema (additive):** new `Case` model + `case_id` links from `Document` /
   `Entry`. Backfill by grouping on `entities.case_number`.
3. **Background worker (`app/jobs/`):** the MVP queue from §7.
4. **New endpoints (`app/routers/cases.py`):** `/cases`, `/cases/{id}` (vault),
   `/cases/{id}/timeline`, `/events?upcoming=`, `/review-queue`,
   `/cases/{id}/similar`.
5. **New UI (`web/`):** port the prototype's shell, wire it to the new
   endpoints, all-Persian chrome, real loading/empty/error states.
6. Move `Eval` + model switcher into a separate admin view.

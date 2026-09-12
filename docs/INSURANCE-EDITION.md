# Insurance edition — what changed and how to run it

Target: a demo of a *legal AI agent* for an insurer (بیمه ایران-style): the
archive is insurance litigation, every case is linked to the statute articles
the court relied on, and every person / company / court is a first-class node.

## 1. Two classifications, related

| | table | what | written by |
|---|---|---|---|
| **Legal context** | `legal_refs` (`LegalReference`) | statute articles, آیین‌نامه clauses, آرای وحدت رویه — the things a court refers to | `data/laws/laws.json` → `scripts/seed_mock.py`; the «قوانین» tab form; `POST /laws` |
| **Case archive** | `legal_cases` (`LegalCase`) | one row per case number: نوع دعوا، رشتهٔ بیمه، مرجع، وضعیت، مرحله، تاریخ‌ها، نتیجه، مبلغ | `casebase.sync_entry()` after every Entry commit / edit |
| people | `persons`, `organizations` | honorific-stripped `norm_name` merges mentions | `sync_entry` |
| relations | `case_parties`, `case_references` | who is in a case (role), which article a case cites (context, used_by) | `sync_entry` |
| graph | `graph_edges` | the same facts flattened to `(src)-[REL]->(dst)` for neighbourhood walks, the Graphviz views and Cypher export | `sync_entry` |

`Entry` gained `legal_refs` (JSON, resolved to `ref_id`s) and `case_id`.
`Case` is no longer derived on every render — `cases.derive_cases()` still folds
entries for the UI, but each derived case now carries `record` = its
`LegalCase` row.

Everything relational is rebuilt from the entries by
`POST /archive/resync` (or `casebase.resync_all`).

## 2. Routing — two new intents

`orchestrator.route()` now returns one of
`query | law | cases | archive | analytics | chat | unclear`.

- **law** → `lawbase.answer_law_question`: FTS over `legal_refs` (a bare
  «ماده ۳۰ قانون بیمه» resolves directly), answer cites articles as `[n]`.
- **cases** → `casebase.answer_case_question`: FTS over `legal_cases`, each hit
  loaded with parties + citations, answer cites case records as `[n]`.
- `query` is unchanged (chunk RAG over documents).

Keyword shortcuts: «ماده ۱۶ … ؟» → law; «پرونده‌های مشابه / سابقهٔ آرا / در چه پرونده» → cases.

Model tools (`app/rag/tools.py`) gained `search_law`, `search_cases`,
`entity_profile`, `case_graph` — all read-only.

## 3. Entry pipeline — human in the loop

`workflow.STEPS`: `classify → extract → references → timeline → similar → labels → commit`.

- `references` (new, no LLM): links the extractor's `legal_refs` to
  `legal_refs` rows by law title + article number; unresolved ones are shown
  at the gate (editable law/article, keep/drop). Anything still unresolved at
  commit becomes a `stub` row so the graph keeps the edge and the law browser
  lists what is missing.
- `commit`: `commit_entry` → Document + Entry, then `casebase.sync_entry`
  builds the case, persons/orgs, citations and edges.

Modes: `review` (one stop), `steps` (stop at every gate), `auto`.

The extractor schema (`_EXTRACT_SYSTEM`) now also asks for
`entities.{case_type, insurance_line, claim_amount, outcome, status, filed_date}`
and `legal_refs[{law, article, context, used_by}]`. Vocabularies:
`orchestrator.CASE_TYPES` (14 dispute types) and `orchestrator.INSURANCE_LINES`.

## 4. UI (Streamlit)

New sections: **۱۵ قوانین و مستندات** (law browser + add article + citing cases),
**۱۶ اشخاص و سازمان‌ها** (profiles: every case, role, counterparties, graph),
**۱۷ ویرایش مدخل‌ها** (full CRUD on an entry — fields, parties, representation,
events, legal refs, tags — save re-syncs case + graph; delete removes the
entry, its document, its case when empty, and orphan persons).

Case detail gained the tab **گراف و مستندات**. Case list gained filters
(نوع دعوا / رشتهٔ بیمه / وضعیت). **۱۱ آمار آرشیو** now works end to end
(clicking a name opens the profile) and shows the case-table aggregates.

The chat (۰۱) renders `law` and `cases` answers with their cited articles /
cases as clickable rows; `unclear` offers five quick intents.

## 5. API

```
GET  /laws?q=…|law_title=…        GET /laws/{id}      POST /laws
GET  /cases?case_type&insurance_line&status&court&q
GET  /cases/search?q=…            GET /cases/{id}     PATCH /cases/{id}
GET  /cases/{id}/graph?depth=1&format=json|dot|cypher
GET  /entities/{person|org}?q=…   GET /entities/{person|org}/{id-or-name}
GET  /graph/{node_type}/{node_id}?depth=&format=
GET  /entries  GET /entries/{id}  PATCH /entries/{id}  DELETE /entries/{id}?with_document=
GET  /archive/stats               POST /archive/resync
POST /assistant  {text, intent?: law|cases|…}
```

## 6. Data

```bash
.venv/bin/python -m scripts.seed_mock --reset --n 120     # deterministic, --seed 7
```
73 articles from `data/laws/laws.json` (gist text — verify against the official
text before real use) + 120 generated cases, ~8–9 per dispute type, each with
exact citations, parties, lawyers, judge, events, outcome, amount. Real cases
enter through the assistant («ثبت مطلب جدید») or `POST /ingest` + the pipeline —
the same `commit_entry` path — never by editing the seed.

## 7. Models

`.env`: `LLM_PROVIDER=anthropic`, `LLM_MODEL=claude-haiku-4-5`,
`ROUTER_MODEL=anthropic::claude-haiku-4-5`, `ANTHROPIC_API_KEY=…` (console.anthropic.com;
needs API credits — a claude.ai Max subscription does not cover API calls).

`LLM_PROVIDER=mock` runs the whole system offline with a rule-based stand-in
(`app/llm/mock_provider.py`): routing by keywords, extraction by regex, answers
as cited summaries of the retrieved evidence. Use it for UI walkthroughs
without spend; switch to Haiku for the real demo.

Embeddings default to `hash://384` (offline). Switch to a real multilingual
model when Hugging Face is reachable, then `python -m scripts.reembed`.

## 8. Run

```bash
uv venv --python 3.12 && uv pip install -r requirements.txt
cp .env.example .env            # put ANTHROPIC_API_KEY in
.venv/bin/python -m scripts.seed_mock --reset --n 120
.venv/bin/streamlit run streamlit_app.py --server.port 8504
# API: .venv/bin/uvicorn app.main:app --port 8000
```

## 9. Known limits

- Persian FTS is `simple` (no stemmer); mitigated by DF filtering.
- `hash://` embeddings are lexical, not semantic — «پرونده‌های مشابه» quality
  is FTS-grade until a real embedding model is installed.
- Law texts are gists; the `exact` flag marks near-verbatim ones.
- Graph export to a real graph DB is `format=cypher` text, not a live Neo4j.

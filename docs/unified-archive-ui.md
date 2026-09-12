# Unified Case Archive — UI transcription

A faithful screen-by-screen transcription of **`legal-archive-unified-2-proposed.html`**
(the "second / proposed" version of the interface mock), for future setup and
rebuild. This is a description of the prototype as it stands — every view, panel,
component, modal, and interaction — not a spec for what it *should* become.

The prototype is a single self-contained HTML file: Vazirmatn + IBM Plex Mono
from Google Fonts, no build step, no framework. All rendering is string-template
functions driving `#mainRoot`. Direction is RTL (`<html dir="rtl" lang="fa">`);
all UI copy is Persian.

- **Title:** دستیار پرونده — آرشیو و هوش مصنوعی حقوقی
- **Favicon:** inline SVG — gold scales-of-justice on a navy disc
- **Persona baked into the mock:** logged in as **فاطمه رضایی**, وکیل پایه یک
  (bar-certified lawyer); access line states confidential cases belonging to
  other users are not shown.

---

## 1. Live vs. demo split

The sidebar footer states it outright:

> دستیار و جستجو: زنده (سرور RAG) — داشبورد و پرونده‌ها: داده نمایشی
> *(Assistant and search: live RAG server — dashboard and cases: demo data)*

| Surface | Data source |
|---|---|
| دستیار پرونده (agent chat) | **Live** — `POST /assistant`, falls back to a local demo responder when the server is unreachable |
| جستجوی معنایی (semantic search) | **Live** — `POST /search`, falls back to showing the anchor case's similar list |
| Draft commit from chat | **Live** — `POST /assistant/commit` |
| Server badge / connection | **Live** — `GET /health` on load and after settings save |
| Everything else (dashboard, case list, case detail, events, ingest pipeline, taxonomy, review queue, analytics) | **Demo** — six hard-coded cases in the `cases` array |

### Live API layer (`API` + `apiCall`)

- Base URL: `localStorage['rag.url']` or `location.origin`
- Token: `localStorage['rag.token']`, sent as `Authorization: Bearer …`
- Model override: `localStorage['rag.model']`, sent as `body.model` on `/assistant`
- Every request carries `ngrok-skip-browser-warning: true`
- `refreshServer()` reads `/health` → `SERVER = { ok, model, provider, docs, auth }`;
  if `auth_required` and no token is stored, the server-settings modal opens with a
  prompt to paste `API_TOKEN` from `.env`.
- `paintServerBadge()` fills every `[data-server-badge]` element: a teal dot +
  `provider · model · N سند` when connected, a red dot + `اتصال ناموفق` / `آفلاین`
  otherwise.

---

## 2. Shell

```
┌───────────┬───────────────────────────────────────────────┐
│  sidebar  │  #mainRoot  (agent shell OR classic topbar +  │
│  (238px)  │              scroll-area + view)               │
└───────────┴───────────────────────────────────────────────┘
```

### Sidebar (`#sidebar`, navy `--ink`)

- **Brand:** gold scales SVG in a circular mark + title **آرشیو هوشمند پرونده** /
  mono sub-label `CASE INTELLIGENCE`.
- **Nav list** (`#navList`) — nine items, each with a mono two-digit Persian
  number, a label, and an optional red count badge:

  | # | id | Label | Badge |
  |---|---|---|---|
  | ۰۱ | `agent` | دستیار پرونده | — |
  | ۰۲ | `dashboard` | داشبورد | — |
  | ۰۳ | `cases` | پرونده‌ها | — |
  | ۰۴ | `events` | رویدادها و یادآورها | — |
  | ۰۵ | `ingest` | دریافت و بایگانی سند | — |
  | ۰۶ | `search` | جستجوی معنایی و مشابه‌یاب | — |
  | ۰۷ | `taxonomy` | طبقه‌بندی و برچسب‌ها | — |
  | ۰۸ | `review` | بازبینی انسانی | count of `needsReview` cases |
  | ۰۹ | `analytics` | آمار و تحلیل | — |

  Active item: white text, left amber border-inset. The `☰` button in either
  header toggles `.collapsed` (width → 0).
- **Footer:** the live/demo split note above.

### Router (`render()`)

`activeView` selects the view. `agent` renders the full-height chat shell
(`agentShellHTML()` + `mountAgent()`). Every other view renders
`classicTopbar()` + a scrollable `.view` body. State held in module scope:
`activeView`, `openCaseId`, `openTab`, `labelFilter`.

---

## 3. Surface A — دستیار پرونده (agent home)

Full-height column: header, scrolling chat, suggestion chips, composer.

### Agent header

- `☰` sidebar toggle
- Avatar **آ** with a status dot (`#statusDot`): grey idle, teal `live`, amber `busy`
- Name **دستیار پرونده** + state line `#ahState` (e.g. «آماده — با تایپ یا صدا بپرسید»,
  «در حال بررسی آرشیو…», «در حال پاسخ صوتی…»)
- Right side: server badge, 🔊/🔇 speak toggle, ⚙ server settings, 📎 attach-demo

### Chat log

- Opening agent message (on empty log) introduces the assistant: archive a case,
  ask about upcoming events, categorise cases, check the human-review queue —
  by typing or by voice.
- User bubbles: navy, right-aligned to the start edge. Agent bubbles: white
  bordered, tagged «دستیار پرونده» + avatar, may embed a **card** widget.
- Typing indicator: three blinking dots while a response is pending.

### Suggestion chips

1. دسته‌بندی پرونده‌های در جریان
2. رویدادهای پیش رو
3. پرونده‌های مشابه
4. صف بازبینی انسانی
5. مثال: ثبت اطلاعات با گفتار — a long dictation example
   («برای پرونده خیانت در امانت، بازپرس گفت مهلت لایحه تا ۱۴۰۳/۰۷/۰۵ تمدید شد»)

### Composer

- 🎙️ mic button — Web Speech API (`SpeechRecognition`, `lang='fa-IR'`,
  interim results). While listening: red pulsing button with an animated 5-bar
  waveform; state line «در حال گوش دادن…». On a final result the input is filled
  and auto-sent. Unsupported browsers get a hint to type instead.
- Auto-growing textarea (max 110px). Enter sends, Shift+Enter newlines.
- ➤ send button.
- TTS: agent replies are spoken via `speechSynthesis` (prefers an `fa-*` voice)
  when the speak toggle is on; `speak` text is a shorter spoken variant.

### Intent handling

**Live (`handleQuery` → `POST /assistant`, body `{ text, model? }`):**

| `j.intent` | Rendered as |
|---|---|
| `query` | `liveAnswerHtml` — answer text with `[n]` citations bolded teal, plus a footer: `N گزیده بازیابی شد · <model> · <s> ثانیه` |
| `analytics` | `j.summary` text + `liveStatsCard(j.stats)` — documents / chunks / structured-record counts, and mini-lists of وکلا / موضوعات / اشخاص |
| `archive` | `liveDraftCard(j)` — extracted draft (عنوان، خلاصه، طرفین، وکالت، شماره پرونده، دادگاه، موضوع) + a **شناسه منبع** input + «تایید و ذخیره در آرشیو» → `POST /assistant/commit` |

Server errors surface as an agent bubble: «⚠ خطا در ارتباط با سرور: …».

**Demo fallback (`handleQueryDemo`)** — regex intent match on the typed text:

| Trigger (regex, Persian) | Card |
|---|---|
| دسته‌بندی + کیفری / حقوقی / جریان\|باز / (none) | `categoryCard` — type & status bar breakdown + case mini-rows |
| بازبینی \| ابهام \| نامشخص | `reviewQueueCard` |
| رویداد \| جلسه \| مهلت \| پیش رو \| این هفته \| نزدیک | `eventsCard` |
| مشابه | `similarCard` for the best-matched case |
| خلاصه | `summaryCard` for the matched case |
| looks like dictation (برای پرونده / ثبت کن / تمدید شد / اعلام کرد / گفت) or contains a date | `captureCard` — matched case, dictated text, detected date, extraction-confidence stamp, «تایید و ثبت در پرونده» |
| no match | capability reminder message |

`attachDemo()` (📎): posts a fake PDF user message, then an agent card matching
the document to case C-2 at 95% confidence.

### Inline card widgets (chat)

- **`categoryCard`** — title + count; horizontal bars for کیفری/حقوقی and
  در جریان / مختومه (موفق) / مختومه (ناموفق); clickable case mini-rows with status stamp.
- **`eventsCard`** — upcoming events (cases with `nextEvent`), sorted by date;
  «مشاهده همه رویدادها» → events view.
- **`similarCard`** — historical similar cases with match-% bars; disclaimer that
  the list is historical, not a prediction.
- **`summaryCard`** — case-id, type, court/branch, next event, match-confidence
  stamp; «مشاهده پرونده کامل».
- **`reviewQueueCard`** — cases needing review with reason; «باز کردن صف کامل بازبینی».
- **`captureCard`** — detected case, dictated text, date, extraction confidence;
  «تایید و ثبت در پرونده» (`confirmCapture` pushes a timeline row) or «انتخاب دستی پرونده».
- **`liveStatsCard` / `liveDraftCard` / `liveAnswerHtml`** — the live-server variants above.

---

## 4. Surface B — classic archive views

### Classic top bar (`classicTopbar()`)

- `☰` toggle + view title (from `titleMap`) + access line:
  «سطح دسترسی: وکیل پایه یک · پرونده‌های محرمانه سایر کاربران نمایش داده نمی‌شود».
- 🔔 bell with a red count badge = number of upcoming events. Panel
  (`#bellPanel`, `toggleBell`): «یادآورهای پیش رو» list; footer note that
  reminders are created by an **independent scheduler, not the language model**,
  and this list is display-only. Closes on outside click.
- Server badge, ⚙ server-settings, 💬 back-to-assistant, user chip (ف.ر / فاطمه رضایی / وکیل پایه یک).

### 4.1 Dashboard (`dashboard`)

- Header actions: «+ پرونده جدید» (new-case modal), «+ بایگانی سند جدید» (ingest modal).
- **Ledger cards** (4, dashed top border, mono numbers):
  پرونده در جریان · رویداد در ۳۰ روز آینده (amber) · نیازمند بازبینی انسانی (red) ·
  میانگین اطمینان تطبیق پرونده ۹۴٪ (teal).
- **Panel «رویدادها و مهلت‌های نزدیک»** — upcoming events as clickable list rows
  (→ case timeline), each with mono date + status stamp.
- **Panel «موارد نیازمند بازبینی انسانی»** — review-needed cases with red reason
  text; «مشاهده صف کامل» → review view. Empty state: «موردی برای بازبینی وجود ندارد».

### 4.2 Case list (`cases`)

- Header: count (+ active label filter), a «حذف فیلتر برچسب» button when filtered,
  an inline search input (`filterList` — title or number substring), «+ پرونده جدید».
- **Table** columns: شماره پرونده · عنوان (+ subject sub-line) · برچسب‌ها (chips) ·
  دادگاه / شعبه · وضعیت (stamp) · رویداد بعدی (mono date).
- Row click → case detail.
- **Case-id rendering (`caseIdHTML`)**: the 15-digit number split `4-3-8` into
  boxed monospace digit cells, forced LTR — evokes a stamped docket number.

### 4.3 Case detail (`case-detail`)

- Back button «→ بازگشت به فهرست پرونده‌ها» + «📄 تولید گزارش پرونده».
- **Cover**: large case-id, title, label chips, status stamp; meta row
  (نوع پرونده، دادگاه، شعبه، موضوع، رویداد بعدی).
- **Folder tabs** (`tabsDef`), file-folder styled:

  | tab | Content |
  |---|---|
  | خلاصه | طرفین list, آخرین وضعیت (last timeline entry), برچسب‌ها + confidentiality chip, وکیل پرونده, **اطمینان تطبیق سیستم** stamp, doc count |
  | تایم‌لاین | vertical timeline; each item date / title / desc / «منبع سند: …»; pending items amber with ⏳, done teal with ✓ |
  | اسناد | doc rows: extension-badge icon, name, type + archive date, review-status stamp, «مشاهده» → preview modal |
  | اطلاعات مالی | 3-col grid: مبلغ خواسته / مبلغ حکم‌شده / حق‌الوکاله توافق‌شده / مبلغ دریافت‌شده (all mono); note that amounts are recorded as-is without currency conversion |
  | پرونده‌های مشابه | disclaimer «historical list, not a prediction» + similar cases with match-% bars and outcomes |
  | اقدامات در انتظار | checklist; clicking a row toggles done (strike-through) |
  | داده ساختاریافته (JSON) | dark JSON box: `case_id, case_number, case_type, subject, court, branch, status, labels, confidentiality, financial_information, confidence, requires_human_review`; note it is shown for technical transparency only |

- **`generateCaseReport`** (report modal): a "generated from archived data" step,
  a compact field table (وضعیت، آخرین رویداد، رویداد بعدی، اقدامات در انتظار،
  اطمینان تطبیق), a warning that the output needs review by the responsible lawyer
  before formal use, and «ارسال برای بازبینی نهایی».

### 4.4 Events & reminders (`events`)

Every timeline entry across all cases, flattened and date-sorted. Rows link to
the case timeline; each carries a «ثبت‌شده» (recorded) or «در انتظار» (pending) stamp.

### 4.5 Ingest & archive (`ingest`)

- Dropzone (PDF / image / Word) + «شبیه‌سازی بارگذاری سند نمونه» → ingest modal.
- **Panel «مراحل خط پردازش سند»** — the pipeline as a text arrow chain:
  اعتبارسنجی سند ← OCR و درک سند ← طبقه‌بندی ← استخراج موجودیت‌ها ← تطبیق با پرونده‌ها
  ← اعتبارسنجی اطلاعات ← ایجاد/به‌روزرسانی پرونده ← استخراج رویداد و اطلاعات مالی
  ← نمایه‌سازی و بایگانی نهایی.
- **Ingest modal** (`runPipeline`): a fixed sample file
  `قرارداد_پیمانکاری_ضمیمه۲.pdf — ۴٫۲ مگابایت`; six pipe steps animate
  active → done at 600ms intervals:

  | Step | Sub-label |
  |---|---|
  | اعتبارسنجی سند | بررسی فرمت، خوانایی و صحت فایل |
  | OCR و درک ساختار سند | استخراج متن، جداول و امضاها |
  | طبقه‌بندی سند | نوع: قرارداد پیمانکاری — دسته: حقوقی / قرارداد |
  | استخراج موجودیت‌ها | طرفین، تاریخ‌ها، مبالغ، شماره پرونده |
  | تطبیق با پرونده‌های موجود | مقایسه با شماره پرونده، طرفین و شعبه |
  | نمایه‌سازی و بایگانی نهایی | افزودن به تایم‌لاین و آرشیو جستجوپذیر |

  Result box: 95% match stamp, "identified as a contract annex and attached to
  case 140201123400089", «مشاهده در پرونده» → C-2 timeline.

### 4.6 Semantic search (`search`)

- Query input; example prompt: «پرونده‌های کلاهبرداری اینترنتی مشابه که منجر به
  محکومیت شده‌اند را نشان بده.» Enter to search.
- **Live** (`runSemanticSearch` → `POST /search`, `top_k: 8`): result panel
  «N نتیجه — جستجوی برداری زنده», each hit: title/source, 160-char snippet,
  match-% + bar. Errors → «خطا در جستجو: …».
- **Offline fallback**: picks an anchor case by fuzzy text match and shows its
  `similar` list under «نتایج مرتبط با: …».

### 4.7 Taxonomy & labels (`taxonomy`)

- Hierarchical tree from the `taxonomy` array:
  - **حقوقی** → ملک (تخلیه، مالکیت، سند) · قرارداد (نقض قرارداد، فسخ) · مالی (مطالبه وجه)
  - **کیفری** → جرائم مالی (کلاهبرداری، خیانت در امانت) · جرائم علیه اموال (سرقت)
- Each leaf is a pill with a live count; clicking sets `labelFilter` and jumps to
  the case list.
- **Candidate label** box (dashed amber): «تخلفات نوظهور رایانه‌ای» — flagged from
  2 recent similar cases, explicitly *not* auto-added to the taxonomy until approved.

### 4.8 Human review queue (`review`)

- One **review card** per `needsReview` case (amber border):
  - title + case-id + «نیاز به بازبینی» stamp
  - **موضوع ابهام** (the uncertainty)
  - **alternatives** grid — each option with its source document
  - **تصمیم موردنیاز** — the decision the user must make
  - actions: «تایید گزینه اول و ثبت» (reveals a confirmation note) · «مشاهده اسناد پرونده»
- Empty state: «در حال حاضر موردی در صف بازبینی نیست».
- Seeded case: **C-4** (خیانت در امانت) — low-quality OCR on the ownership document
  and a filing-date conflict between the complaint form and the registry scan.

### 4.9 Analytics (`analytics`)

- Ledger cards: پرونده کیفری · پرونده حقوقی · مختومه به نفع موکل (teal) ·
  مختومه به ضرر موکل (red).
- **یادداشت تحلیلی** — a descriptive finding ("among closed eviction cases, most
  ended in the landlord's favour") with the explicit caveat that it is descriptive
  and not a guarantee for future cases.

---

## 5. Modals

| id | Title | Contents |
|---|---|---|
| `ingestOverlay` | پردازش سند جدید | dropzone + animated pipe steps + result box |
| `docOverlay` | (document name) | metadata-only preview: نوع سند، پرونده مرتبط، تاریخ بایگانی، وضعیت بازبینی; note that content preview is not simulated; review warning when the doc `نیاز به بازبینی` |
| `reportOverlay` | تولید گزارش پرونده | generated case report + review-required disclaimer + «ارسال برای بازبینی نهایی» |
| `newCaseOverlay` | ایجاد پرونده جدید | form: نوع پرونده (حقوقی/کیفری), موضوع, عنوان, دادگاه, شعبه, طرفین (one per line); hint that case number and other official fields are filled after registration in the judiciary system and **are not guessed**; `submitNewCase` appends a case with `number: "—"`, `confidence: 0.3` |
| `cfgOverlay` | اتصال به سرور | آدرس سرور + توکن API (from `.env`); «ذخیره و بررسی» saves to localStorage and re-runs `/health` |

Overlay helpers: `openOverlay` / `closeOverlay` toggle `.show`.

---

## 6. Sample data model (`cases`)

Six demo cases (C-1…C-6). Per-case shape:

```
id, number (15-digit string or "—"), title, type ("حقوقی" | "کیفری"), subject,
labels[], confidentiality ("عادی" | "محرمانه"),
court, branch, status ("open" | "closed-win" | "closed-loss"), statusLabel,
priority ("normal" | "urgent"),
parties[] (free-text "role: name"), lawyer, nextEvent {date, title} | null, confidence (0–1),
documents[]  { name, type, date, status },
timeline[]   { date, title, desc, src, pending },
financial    { claimed, awarded, fee, received },
similar[]    { title, match (0–100), outcome },
pending[]    (free-text action strings),
needsReview?, reviewReason?, reviewDetails? { uncertain, alternatives[{label, src}], decision }
```

Seeded cases: C-1 کلاهبرداری اینترنتی (کیفری, urgent), C-2 مطالبه وجه پیمانکاری
(حقوقی), C-3 تخلیه ملک تجاری (closed-win), C-4 خیانت در امانت (needsReview),
C-5 نقض قرارداد تجاری (closed-loss), C-6 سرقت مسلحانه (کیفری, urgent).

`statusMeta` maps status → stamp class + label. Dates are Jalali strings in
Persian digits; all counts render via `toLocaleString('fa-IR')`.

---

## 7. Shared components & tokens

### Stamps (`stampHTML`, `confStamp`) — dashed-border pills

`open` / `closed-win` teal · `closed-loss` grey · `review` amber · `urgent` red.
Confidence stamp: ≥85% teal, 60–84% amber, <60% red — «اطمینان تطبیق N٪».

### Other primitives

`case-id` boxed-digit docket number · `chip` label pill · `ledger-card` KPI tile ·
`panel` / `panel-head` / table · `folder-tab` · timeline `tl-item` ·
`doc-row` · `fin-box` · `sim-row` match bar · `json-box` (dark, LTR) ·
`pipe-step` (opacity + icon states) · `review-card` · `tax-leaf`.

### Design tokens

| token | value | role |
|---|---|---|
| `--ink` | `#142236` | navy — sidebar, primary text/buttons |
| `--paper` | `#F3F0E7` | warm archival background |
| `--surface` | `#FFFFFF` | cards/panels |
| `--line` | `#E1DAC7` | borders |
| `--stamp-red` | `#7C2D2D` | urgent / criminal / errors |
| `--teal` | `#0F4C3A` | open / success / live |
| `--amber` | `#9C7209` | review / pending |
| `--gray` | `#6E6858` | muted / closed-loss |
| `--gold` | `#A9812E` | brand accent |

Fonts: **Vazirmatn** (400–800) for UI; **IBM Plex Mono** for numbers, dates,
case-ids, JSON. Radius `12px`. Single light theme, no dark mode.

---

## 8. Safety / disclaimer language (used verbatim throughout)

- Reminders are created by an **independent scheduler, not the language model**.
- Similar-case lists are **historical, not predictions** of the current case.
- Analytics findings are **descriptive**, not guarantees.
- Generated case reports **require review by the responsible lawyer** before formal use.
- New-case official fields (case number, etc.) are **filled after registration,
  not guessed**.
- Low-OCR-quality documents are flagged and routed to **human review**; extracted
  content from them is not treated as confirmed.
- Confidential cases of other users are **not shown** at this access level.

---

## 9. Live endpoints the UI depends on

| Call | Used by |
|---|---|
| `GET /health` | server badge, auth prompt (`llm_available`, `llm_model`, `llm_provider`, `indexed_documents`, `auth_required`) |
| `POST /assistant` `{text, model?}` → `{intent, answer/summary/draft, contexts, model, latency_ms, stats}` | agent chat |
| `POST /assistant/commit` `{draft, raw_text, source}` | «تایید و ذخیره در آرشیو» |
| `POST /search` `{query, top_k}` → `{hits:[{title, source, text, similarity}]}` | semantic search |

Model switching is via `localStorage['rag.model']` only — there is no model
picker in this prototype's UI (that lives in the developer `index.html`).

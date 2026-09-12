"""
The orchestration layer.

One entry point — run_assistant() — takes a piece of text (typed, or the
transcript of something dictated) and decides what to do with it:

  intent = "query"      -> answer it from the archive (the RAG pipeline)
  intent = "archive"    -> extract a structured Entry and return it as a
                           *draft* for the user to confirm (never auto-writes)
  intent = "analytics"  -> compute corpus stats and, on request, an LLM summary

commit_entry() is the second half of the archive flow: it stores the
confirmed draft as an Entry *and* as a Document (chunked + embedded) so the
material is both structurally queryable and retrievable by vector search,
then links it to related existing entries.
"""

import json
import os
import re
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Chunk, Document, Entry, Label
from app.llm.base import LLMProvider
from app.rag.ingest import ingest_document
from app.rag.pipeline import answer_question
from app.rag.retriever import retrieve_scored

# The five things a message can be. `chat` and `unclear` are new: without them
# the router's fallback default was `archive`, so any statement it could not
# place became a proposed Entry — greetings, tasks, half-typed fragments and all.
VALID_INTENTS = {"query", "law", "cases", "agent", "archive", "analytics", "chat", "unclear"}

_INTENT_FA = {
    "query": "پرسش از اسناد",
    "law": "پرسش از قوانین",
    "cases": "جستجوی بایگانی پرونده‌ها",
    "agent": "پژوهش عاملی",
    "archive": "ثبت مطلب جدید",
    "analytics": "آمار آرشیو",
    "chat": "گفت‌وگو",
    "unclear": "نامشخص",
}

# Insurance-domain vocabularies the extractor and the case table share. Free
# text is still accepted; these are what the seed uses and the UI filters on.
CASE_TYPES = [
    "مطالبه خسارت بیمه‌گذار علیه بیمه‌گر", "دفاع بیمه‌گر: بطلان / تعلیق / قاعده نسبی",
    "جانشینی / بازیافت", "شخص ثالث — خسارت بدنی/مالی", "بازیافت از راننده مقصر",
    "صندوق تأمین خسارت‌های بدنی", "حوادث ناشی از کار / مسئولیت کارفرما",
    "رجوع تأمین اجتماعی (م. ۶۶)", "تقلب / جعل / کلاهبرداری بیمه‌ای",
    "دعاوی نمایندگان و کارگزاران", "دعاوی استخدامی کارکنان",
    "اعتراض به بیمه مرکزی / شورای عالی بیمه", "داوری قراردادی", "دعاوی رشته‌محور",
]
INSURANCE_LINES = [
    "شخص ثالث", "حوادث راننده", "بدنه خودرو", "درمان تکمیلی", "عمر و سرمایه‌گذاری",
    "عمر زمانی", "حوادث انفرادی", "حوادث گروهی", "آتش‌سوزی", "باربری", "کشتی", "هواپیما",
    "پول", "مسئولیت مدنی کارفرما", "مسئولیت حرفه‌ای پزشکان", "مسئولیت تولیدکننده کالا",
    "مسئولیت مدیران", "مهندسی (CAR/EAR)", "شکست ماشین‌آلات", "عدم‌النفع", "اعتبار",
    "نفت و انرژی", "کشاورزی", "اتکایی",
]

# Human-readable description of the structured record the archive flow produces.
# The UI uses this to render a guided form and explain what it is capturing —
# so a user never has to know the JSON shape.
ENTRY_SCHEMA = {
    "title": "این ساختاری است که سیستم از متن جلسه/سند بیرون می‌کشد و ذخیره می‌کند.",
    "fields": [
        {"key": "title", "label": "عنوان", "type": "text", "help": "یک عنوان کوتاه برای مدخل"},
        {"key": "summary", "label": "چکیده", "type": "text", "help": "خلاصهٔ یک‌بندی به زبان متن"},
        {"key": "kind", "label": "نوع", "type": "choice", "options": ["session", "note"],
         "help": "صورت‌جلسه یا یادداشت"},
        {"key": "parties", "label": "طرفین", "type": "list",
         "item": {"name": "نام", "role": "نقش"},
         "roles": {"khahan": "خواهان", "khande": "خوانده", "vakil_khahan": "وکیل خواهان",
                   "vakil_khande": "وکیل خوانده", "ghazi": "قاضی", "mottaham": "متهم",
                   "shaki": "شاکی", "other": "سایر"},
         "help": "هر شخص/شرکت درگیر و نقش او در پرونده"},
        {"key": "representation", "label": "وکالت", "type": "list",
         "item": {"lawyer": "وکیل", "client": "موکل"},
         "help": "چه کسی وکیلِ چه کسی بوده"},
        {"key": "events", "label": "رویدادها", "type": "list",
         "item": {"date": "تاریخ", "description": "شرح"},
         "help": "جلسات، مهلت‌ها، تصمیمات — با تاریخ"},
        {"key": "entities.case_number", "label": "شماره پرونده", "type": "text",
         "help": "شمارهٔ کلاسه — کلید تجمیع پرونده‌ها"},
        {"key": "entities.court", "label": "دادگاه", "type": "text", "help": "مرجع رسیدگی"},
        {"key": "entities.topic", "label": "موضوع", "type": "text", "help": "موضوع دعوا"},
        {"key": "entities.case_type", "label": "نوع دعوا", "type": "choice", "options": CASE_TYPES,
         "help": "دسته‌بندی حقوقی پرونده در صنعت بیمه"},
        {"key": "entities.insurance_line", "label": "رشتهٔ بیمه", "type": "choice", "options": INSURANCE_LINES,
         "help": "رشتهٔ بیمه‌ای موضوع پرونده"},
        {"key": "entities.claim_amount", "label": "مبلغ خواسته (ریال)", "type": "text", "help": "مبلغ خسارت/خواسته"},
        {"key": "entities.outcome", "label": "نتیجه", "type": "text", "help": "رأی یا وضعیت نهایی"},
        {"key": "entities.status", "label": "وضعیت", "type": "choice", "options": ["open", "closed", "appeal", "archived"],
         "help": "جاری / مختومه / تجدیدنظر / بایگانی"},
        {"key": "entities.filed_date", "label": "تاریخ طرح", "type": "text", "help": "تاریخ شمسی"},
        {"key": "legal_refs", "label": "مستندات قانونی", "type": "list",
         "item": {"law": "قانون", "article": "ماده", "context": "نحوهٔ استناد"},
         "help": "موادی که دادگاه یا طرفین به آن استناد کرده‌اند — به پایگاه قوانین متصل می‌شود"},
        {"key": "entities.people", "label": "اشخاص", "type": "taglist", "help": "نام اشخاص ذکرشده"},
        {"key": "entities.orgs", "label": "سازمان‌ها", "type": "taglist", "help": "نام سازمان‌ها/شرکت‌ها"},
        {"key": "tags", "label": "برچسب‌ها", "type": "taglist", "help": "برچسب‌های دسته‌بندی"},
    ],
}

_ROUTER_SYSTEM = (
    "You route a message in a Persian legal-archive assistant. Reply with JSON "
    "only:\n"
    '  {"intent": "...", "confidence": 0.0-1.0, "clarify": "" }\n'
    "\n"
    "intent is exactly one of:\n"
    '- "query": the user asks a QUESTION to be answered from the archive — about '
    "a case, a ruling, a person, what happened. Often ends with ؟ or contains "
    "چه/چگونه/کدام/آیا/چرا, or asks to show/find/list specific records.\n"
    '- "law": asks what the LAW says — the text or meaning of an article, a '
    "statute, a regulation, a precedent; a legal rule in the abstract (طبق قانون "
    "بیمه...، ماده ۳۰ چه می‌گوید، مرور زمان دعاوی بیمه چقدر است). Answered from "
    "the legal-context base with article citations.\n"
    '- "cases": asks the CASE ARCHIVE for precedents or records — cases about a '
    "topic, cases of a lawyer/company/insurer, how similar cases ended, which "
    "articles cases like this relied on (پرونده‌های مشابه، سابقهٔ آرای جانشینی، "
    "پرونده‌های وکیل کریمی). Answered from the structured case table.\n"
    '- "analytics": asks for a COUNT, an aggregate or an overview of the whole '
    "archive (چند، تعداد، آمار، فهرست همهٔ...).\n"
    '- "archive": the user is RECORDING something that happened, for the file — '
    "a court session, hearing or meeting, narrated as past events with parties, "
    "a judge and/or a decision, and NOT asking anything. If it reads like a "
    "question about a case rather than a report of one, it is \"query\", not "
    '"archive".\n'
    '- "chat": greetings, thanks, small talk, a request to the assistant itself '
    "(translate this, summarise that, what can you do), or anything not about "
    "the archive's contents. Answer conversationally, retrieve nothing, store "
    "nothing.\n"
    '- "unclear": you genuinely cannot tell, or the message is too short or '
    "fragmentary to route. Put a short Persian question in \"clarify\" that "
    "would resolve it.\n"
    "\n"
    "Set confidence to how sure you are. Use \"unclear\" whenever confidence "
    "would be below ~0.55 — guessing wrong and filing a stray Entry is worse "
    "than asking.\n"
    "\n"
    "Examples:\n"
    'در پرونده کالای معیوب دادگاه چه تصمیمی گرفت؟ -> {"intent":"query","confidence":0.95,"clarify":""}\n'
    'ماده ۳۰ قانون بیمه دربارهٔ جانشینی چه می‌گوید؟ -> {"intent":"law","confidence":0.96,"clarify":""}\n'
    'مرور زمان دعاوی بیمه چند سال است؟ -> {"intent":"law","confidence":0.9,"clarify":""}\n'
    'پرونده‌های بازیافت از رانندهٔ فاقد گواهینامه چطور تمام شده‌اند؟ -> {"intent":"cases","confidence":0.93,"clarify":""}\n'
    'وکیل کریمی در چه پرونده‌هایی بوده؟ -> {"intent":"cases","confidence":0.9,"clarify":""}\n'
    'امروز جلسه پرونده ۱۴۰۲۱۱ برگزار شد. خواهان شرکت الف با وکالت آقای کریمی بود. '
    'قاضی پرونده را به کارشناسی ارجاع داد. -> {"intent":"archive","confidence":0.9,"clarify":""}\n'
    'چند پرونده کارگری داریم؟ -> {"intent":"analytics","confidence":0.92,"clarify":""}\n'
    'سلام، خوبی؟ -> {"intent":"chat","confidence":0.97,"clarify":""}\n'
    'این متن رو خلاصه کن -> {"intent":"chat","confidence":0.8,"clarify":""}\n'
    'کریمی -> {"intent":"unclear","confidence":0.3,"clarify":"دربارهٔ آقای کریمی چه می‌خواهید؟ پرونده‌هایش را ببینید یا مطلبی ثبت کنید؟"}'
)

_EXTRACT_SYSTEM = (
    "Extract structured data from a legal session or note. The text is usually "
    "Persian; keep names and values in their original script. Reply with JSON "
    "only, matching this shape exactly:\n"
    "{\n"
    '  "kind": "session" | "note",\n'
    '  "title": string,\n'
    '  "summary": string (one paragraph, same language as the input),\n'
    '  "parties": [{"name": string, "role": "khahan" | "khande" | '
    '"vakil_khahan" | "vakil_khande" | "ghazi" | "mottaham" | "shaki" | "other"}],\n'
    '  "representation": [{"lawyer": string, "client": string}],\n'
    '  "events": [{"date": string, "description": string}],\n'
    '  "entities": {"people": [string], "orgs": [string], "case_number": string, '
    '"court": string, "topic": string, "case_type": string, "insurance_line": string, '
    '"claim_amount": string, "outcome": string, "status": "open" | "closed" | "appeal", '
    '"filed_date": string},\n'
    '  "legal_refs": [{"law": string, "article": string, "context": string, '
    '"used_by": "court" | "plaintiff" | "defendant"}],\n'
    '  "tags": [string]\n'
    "}\n"
    'Use "" or [] where unknown. "representation" is who acted for whom '
    "(lawyer -> client). \"legal_refs\" lists every statute article, regulation "
    "or precedent the text cites (e.g. law=\"قانون بیمه\", article=\"30\") with "
    "how it was used. \"case_type\" is one of: " + " | ".join(CASE_TYPES) + ". "
    "\"insurance_line\" is one of: " + " | ".join(INSURANCE_LINES) + ". "
    "\"claim_amount\" is the amount claimed in Rials as digits only."
)


def _parse_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
    return {}


# How sure the router must be before we act on its guess. Below this it returns
# "unclear" and asks, because filing a wrong Entry is costlier than a question.
_ROUTE_CONFIDENCE_FLOOR = 0.55

# When ROUTER_MODEL is set the router uses it instead of the answer model — the
# classification is a tiny call and does not need a large reasoning model, and
# pinning it keeps routing fast even when the answer model is slow.
_ROUTER_MODEL = os.environ.get("ROUTER_MODEL", "")


def _router_llm(fallback: LLMProvider) -> LLMProvider:
    if not _ROUTER_MODEL:
        return fallback
    try:
        from app.llm import registry

        candidate = registry.resolve(_ROUTER_MODEL)
        return candidate if candidate.is_available() else fallback
    except Exception:  # noqa: BLE001 — a bad ROUTER_MODEL must not break routing
        return fallback


@dataclass
class Route:
    """The router's decision. One vocabulary, shared by both executors."""

    intent: str                       # query | archive | analytics | chat | unclear
    confidence: float = 0.0
    clarification: str = ""            # a question to ask, when intent == "unclear"
    reason: str = ""                   # for the pipeline trace / debugging


# A few high-precision shortcuts that skip the model call for obvious messages.
# Everything else — including anything ambiguous — goes to the router.
_ANALYTICS_HINT = ("چند ", "چندتا", "تعداد ", "آمار", "چند پرونده", "چند مدخل")
_LAW_RX = re.compile(r"(?:ماد[هۀ]|تبصر[هۀ])\s*[0-9۰-۹]+")
_CASES_HINT = ("پرونده‌های مشابه", "پرونده های مشابه", "سابقهٔ آرا", "سابقه آرا", "رویهٔ", "در چه پرونده")
_GREETING = ("سلام", "درود", "خداحافظ", "ممنون", "مرسی", "متشکرم", "hi", "hello", "thanks")


async def route(llm: LLMProvider, text: str, *, forced: str | None = None) -> Route:
    """Decide what to do with a message.

    `forced` (from the UI's «نوع پیام» selector) skips the model entirely. An
    obvious greeting or count is shortcut without a call. Everything else is
    classified by `_router_llm(llm)` and, when its confidence is low, comes back
    as `unclear` with a clarifying question rather than a bad guess.
    """
    stripped = text.strip()
    if forced in VALID_INTENTS:
        return Route(intent=forced, confidence=1.0, reason="انتخاب دستی")

    if not stripped:
        return Route(intent="unclear", clarification="پیامی وارد نشده — چه کاری انجام دهم؟")

    lowered = stripped.lower()
    if len(stripped) <= 30 and any(g in lowered for g in _GREETING):
        return Route(intent="chat", confidence=0.9, reason="احوال‌پرسی")
    if any(h in lowered for h in _ANALYTICS_HINT):
        return Route(intent="analytics", confidence=0.8, reason="واژهٔ شمارشی")
    if _LAW_RX.search(stripped) and any(m in stripped for m in ("؟", "?", "چه", "چیست", "میگوید", "می‌گوید")):
        return Route(intent="law", confidence=0.85, reason="ارجاع به مادهٔ قانونی")
    if any(h in stripped for h in _CASES_HINT):
        return Route(intent="cases", confidence=0.8, reason="درخواست سابقهٔ پرونده")

    try:
        resp = await _router_llm(llm).generate(
            f"Message:\n{stripped}",
            system=_ROUTER_SYSTEM,
            max_tokens=120,
            json_mode=True,
            reasoning_effort="low",
        )
        data = _parse_json(resp.text)
        intent = str(data.get("intent", "")).lower().strip()
        confidence = float(data.get("confidence") or 0.0)
        clarify = str(data.get("clarify") or "").strip()
    except Exception:  # noqa: BLE001 — gateways may reject strict JSON mode
        intent, confidence, clarify = "", 0.0, ""

    if intent not in VALID_INTENTS:
        # The model failed us. Fall back to the cheapest safe reading: a marked
        # question is a query, otherwise ask rather than assume it is an Entry.
        if any(m in stripped for m in ("؟", "?")):
            return Route(intent="query", confidence=0.4, reason="پرسش‌نما، بدون مسیریاب")
        return Route(
            intent="unclear", confidence=0.0,
            clarification="منظورتان پرسش از آرشیو است، ثبت مطلب جدید، یا آمار؟",
            reason="مسیریاب پاسخ معتبری نداد",
        )

    if intent == "unclear" or (
        intent == "archive" and confidence < _ROUTE_CONFIDENCE_FLOOR
    ):
        return Route(
            intent="unclear", confidence=confidence,
            clarification=clarify or "منظورتان ثبت این مطلب در آرشیو است یا پرسشی درباره‌اش؟",
            reason=f"اطمینان پایین ({confidence:.0%})",
        )

    return Route(intent=intent, confidence=confidence, reason=f"اطمینان {confidence:.0%}")


async def classify_intent(llm: LLMProvider, text: str) -> str:
    """Back-compat: the bare intent string. New code should call `route()`."""
    return (await route(llm, text)).intent


async def extract_entry(llm: LLMProvider, text: str) -> dict:
    # 900 tokens was too tight for a full court-ruling text: a reasoning model
    # (e.g. Groq gpt-oss-120b) can spend the whole completion budget on hidden
    # reasoning and leave nothing for the JSON itself, which Groq's own
    # response_format=json_object validator then rejects with a 400 rather
    # than the finish_reason="length" case the providers already handle.
    # Extraction is deterministic, not a task that benefits from deep
    # reasoning, so pin effort low too — providers that don't support the knob
    # ignore it.
    resp = await llm.generate(
        f"Text:\n{text}",
        system=_EXTRACT_SYSTEM,
        max_tokens=3000,
        json_mode=True,
        reasoning_effort="low",
    )
    data = _parse_json(resp.text)
    # normalise so the caller/UI can rely on the shape
    data.setdefault("kind", "session")
    data.setdefault("title", "")
    data.setdefault("summary", "")
    for key in ("parties", "representation", "events", "tags"):
        if not isinstance(data.get(key), list):
            data[key] = []
    ent = data.get("entities")
    if not isinstance(ent, dict):
        ent = {}
    for key in ("people", "orgs"):
        v = ent.get(key)
        ent[key] = [str(x) for x in v] if isinstance(v, list) else ([str(v)] if v else [])
    for key in ("case_number", "court", "topic", "case_type", "insurance_line", "claim_amount",
                "outcome", "status", "filed_date"):
        v = ent.get(key)
        ent[key] = ", ".join(str(x) for x in v) if isinstance(v, list) else (str(v) if v else "")
    data["entities"] = ent
    refs = data.get("legal_refs")
    clean_refs = []
    for r in (refs if isinstance(refs, list) else []):
        if isinstance(r, str):
            r = {"text": r}
        if isinstance(r, dict) and (r.get("law") or r.get("text")):
            clean_refs.append({
                "law": str(r.get("law") or ""), "article": str(r.get("article") or ""),
                "context": str(r.get("context") or ""), "used_by": str(r.get("used_by") or ""),
                "text": str(r.get("text") or ""),
            })
    data["legal_refs"] = clean_refs
    return data


async def find_related(
    session: AsyncSession, text: str, *, exclude_source: str | None = None, top_k: int = 4
) -> list[dict]:
    scored = await retrieve_scored(session, text, top_k=top_k + 1)
    out = []
    for chunk, distance in scored:
        if exclude_source and chunk.document.source == exclude_source:
            continue
        out.append(
            {
                "document_id": str(chunk.document_id),
                "title": chunk.document.title or chunk.document.source,
                "source": chunk.document.source,
                "similarity": round(1.0 - distance, 3),
            }
        )
    return out[:top_k]


_HONORIFICS = ("جناب آقای ", "سرکار خانم ", "آقای ", "خانم ", "جناب ", "دکتر ", "مهندس ")


def _norm_name(name: str) -> str:
    """Light entity resolution: drop honorifics and collapse whitespace so
    "آقای رضا کریمی" and "رضا کریمی" aggregate together."""
    n = " ".join((name or "").split())
    for h in _HONORIFICS:
        if n.startswith(h):
            n = n[len(h):]
            break
    return n.strip()


async def corpus_stats(session: AsyncSession) -> dict:
    docs = await session.scalar(select(func.count()).select_from(Document))
    chunks = await session.scalar(select(func.count()).select_from(Chunk))
    entries = await session.scalar(select(func.count()).select_from(Entry))

    topics: dict[str, int] = {}
    people: dict[str, int] = {}
    orgs: dict[str, int] = {}
    lawyers: dict[str, int] = {}
    def _as_list(v):
        return v if isinstance(v, list) else ([v] if v else [])

    def _as_str(v):
        return ", ".join(str(x) for x in v) if isinstance(v, list) else (str(v) if v else "")

    for row in (await session.execute(select(Entry.entities, Entry.representation))).all():
        ent = row[0] if isinstance(row[0], dict) else {}
        rep = _as_list(row[1])
        t = _as_str(ent.get("topic")).strip()
        if t:
            topics[t] = topics.get(t, 0) + 1
        for p in _as_list(ent.get("people")):
            p = _norm_name(str(p))
            if p:
                people[p] = people.get(p, 0) + 1
        for o in _as_list(ent.get("orgs")):
            o = " ".join(str(o).split())
            if o:
                orgs[o] = orgs.get(o, 0) + 1
        for r in rep:
            if not isinstance(r, dict):
                continue
            lw = _norm_name(str(r.get("lawyer") or ""))
            cl = _norm_name(str(r.get("client") or ""))
            # drop extraction noise: placeholders and self-representation
            if not lw or lw == cl or "نامشخص" in lw or "نامعلوم" in lw:
                continue
            lawyers[lw] = lawyers.get(lw, 0) + 1

    def top(d: dict, n: int = 10) -> list[dict]:
        return [
            {"name": k, "count": v}
            for k, v in sorted(d.items(), key=lambda kv: -kv[1])[:n]
        ]

    return {
        "documents": docs,
        "chunks": chunks,
        "entries": entries,
        "topics": top(topics),
        "people": top(people),
        "orgs": top(orgs),
        "lawyers": top(lawyers),
    }




async def attach_provenance(
    session: AsyncSession, llm: LLMProvider, intent: str, question: str, res: dict, *,
    source: str = "api", persist: bool = True,
) -> dict:
    """Add the `provenance` block (and persist the answer) to a law / cases /
    query result. The evidence is whatever that route numbered `[n]`."""
    from app.rag import provenance as prov

    if intent == "law":
        evidence = prov.evidence_from_refs(res.get("refs") or [])
    elif intent == "cases":
        evidence = prov.evidence_from_cases(res.get("cases") or [])
    else:
        evidence = prov.evidence_from_contexts(res.get("contexts") or [])
    # The similar-case stage numbers its cases after the route's own evidence
    # and its advice cites them — one ledger, one check.
    evidence = evidence + list(res.get("similar_evidence") or [])
    checked = res.get("answer") or ""
    if res.get("advice"):
        checked += "\n\n" + res["advice"]
    usage = dict(res.get("usage") or {})
    for key, value in (res.get("advice_usage") or {}).items():
        if isinstance(value, (int, float)):
            usage[key] = usage.get(key, 0) + value
    block = prov.build_provenance(
        intent=intent, provider=getattr(llm, "name", None), model=res.get("model"),
        evidence=evidence, tool_trail=res.get("tool_log") or [], usage=usage,
        answer=checked, latency_ms=res.get("latency_ms"),
        extra={"similar_cases": len(res.get("similar_cases") or [])} if res.get("similar_cases") else None,
    )
    res["provenance"] = block
    if persist:
        res["answer_id"] = await prov.persist_answer(
            session, intent=intent, question=question, answer=checked,
            provenance=block, model=res.get("model"), source=source,
        )
    return block


async def similar_stage(session: AsyncSession, llm: LLMProvider, intent: str, question: str, res: dict) -> dict:
    """Run the similar-case stage for a finished law / cases / query result and
    merge its keys (`similar_cases`, `lessons`, `advice`, …) into `res`."""
    from app.rag import similar

    if not similar.enabled() or not res.get("answer"):
        return res
    kwargs: dict = {}
    if intent == "law":
        kwargs = {"refs": res.get("refs") or [], "offset": len(res.get("refs") or [])}
    elif intent == "cases":
        kwargs = {"seed_cases": res.get("cases") or [], "offset": len(res.get("cases") or [])}
    else:
        contexts = res.get("contexts") or []
        kwargs = {"seed_document_ids": [c.get("document_id") for c in contexts if c.get("document_id")],
                  "offset": len(contexts)}
    try:
        extra = await similar.stage(session, llm, question=question, answer=res["answer"], **kwargs)
    except Exception as error:  # noqa: BLE001 — the answer stands without the second stage
        extra = {"steps": [{"name": "پرونده‌های مشابه از گراف", "detail": f"ناموفق: {type(error).__name__}: {error}"[:200]}]}
    steps = list(res.get("steps") or []) + list(extra.pop("steps", []) or [])
    res.update(extra)
    res["steps"] = steps
    return res


async def run_assistant(
    session: AsyncSession, llm: LLMProvider, text: str, *, force_intent: str | None = None,
    source: str = "api",
) -> dict:
    import time as _t

    steps: list[dict] = []
    _s = _t.perf_counter()
    decision = await route(llm, text, forced=force_intent)
    intent = decision.intent
    steps.append({
        "name": "مسیریاب",
        "detail": f"«{_INTENT_FA.get(intent, intent)}» — {decision.reason}",
        "ms": round((_t.perf_counter() - _s) * 1000),
    })

    if intent == "unclear":
        return {
            "intent": "unclear",
            "clarification": decision.clarification,
            "confidence": decision.confidence,
            "steps": steps,
        }

    if intent == "chat":
        _s = _t.perf_counter()
        resp = await llm.generate(
            text,
            system=(
                "You are the assistant of a Persian legal archive. Reply briefly "
                "and helpfully in the user's language. You have not looked "
                "anything up in the archive for this message — if they want that, "
                "invite them to ask a question about a case."
            ),
            max_tokens=1200, reasoning_effort="low",
        )
        steps.append({
            "name": "پاسخ گفت‌وگویی",
            "detail": "بدون بازیابی از آرشیو",
            "ms": round((_t.perf_counter() - _s) * 1000),
        })
        return {
            "intent": "chat",
            "answer": resp.text,
            "model": getattr(resp, "model", None),
            "latency_ms": getattr(resp, "latency_ms", None),
            "steps": steps,
        }

    if intent == "query" and os.environ.get("AGENT_FOR_QUERY", "0") == "1":
        intent = "agent"

    if intent == "agent":
        from app.rag.agent import answer_with_tools

        res = await answer_with_tools(session, llm, text, source=source)
        return {"intent": "agent", **res, "steps": steps + res.get("steps", [])}

    if intent == "law":
        from app.rag.lawbase import answer_law_question

        res = await answer_law_question(session, llm, text)
        await similar_stage(session, llm, "law", text, res)
        await attach_provenance(session, llm, "law", text, res, source=source)
        return {"intent": "law", **res, "steps": steps + res.get("steps", [])}

    if intent == "cases":
        from app.rag.casebase import answer_case_question

        res = await answer_case_question(session, llm, text)
        await similar_stage(session, llm, "cases", text, res)
        await attach_provenance(session, llm, "cases", text, res, source=source)
        return {"intent": "cases", **res, "steps": steps + res.get("steps", [])}

    if intent == "query":
        rag = await answer_question(session, llm, text, top_k=5)
        res = {
            "answer": rag.answer,
            "contexts": rag.contexts,
            "model": rag.model,
            "latency_ms": rag.latency_ms,
            "usage": {"calls": 1, "input_tokens": rag.input_tokens or 0,
                      "output_tokens": rag.output_tokens or 0, "latency_ms": round(rag.latency_ms or 0)},
            "reasoning": rag.reasoning,
            "steps": rag.steps,
        }
        await similar_stage(session, llm, "query", text, res)
        await attach_provenance(session, llm, "query", text, res, source=source)
        return {"intent": "query", **res, "steps": steps + res["steps"]}

    if intent == "archive":
        _s = _t.perf_counter()
        draft = await extract_entry(llm, text)
        got = [k for k in ("title", "summary") if draft.get(k)]
        got += [f"{len(draft.get('parties', []))} طرف", f"{len(draft.get('events', []))} رویداد"]
        steps.append({
            "name": "استخراج ساختاریافته",
            "detail": f"مدل فیلدهای مدخل را از متن بیرون کشید: {'، '.join(got)}",
            "ms": round((_t.perf_counter() - _s) * 1000),
        })
        _s = _t.perf_counter()
        related = await find_related(session, text)
        steps.append({
            "name": "یافتن مدخل‌های مرتبط",
            "detail": f"جستجوی معنایی در آرشیو → {len(related)} مورد مرتبط",
            "ms": round((_t.perf_counter() - _s) * 1000),
        })
        return {
            "intent": "archive",
            "draft": draft,
            "raw_text": text,
            "related": related,
            "committed": False,
            "steps": steps,
            "schema": ENTRY_SCHEMA,
        }

    _s = _t.perf_counter()
    stats = await corpus_stats(session)
    steps.append({
        "name": "تجمیع پایگاه‌داده",
        "detail": f"شمارش SQL روی {stats['entries']} مدخل — بدون فراخوانی مدل",
        "ms": round((_t.perf_counter() - _s) * 1000),
    })
    summary = ""
    if stats["entries"]:
        rows = (
            await session.execute(
                select(Entry.title, Entry.summary).order_by(Entry.created_at.desc()).limit(20)
            )
        ).all()
        listing = "\n".join(f"- {r.title}: {r.summary}" for r in rows if r.summary)
        _s = _t.perf_counter()
        resp = await llm.generate(
            f"Question: {text}\n\nArchive entries:\n{listing}",
            system=(
                "Answer the question about the archive using the entry list. "
                "Reply in the same language as the question. Be concise."
            ),
            max_tokens=1200, reasoning_effort="low",
        )
        summary = resp.text
        steps.append({
            "name": "خلاصهٔ زبانی",
            "detail": f"مدل {getattr(resp, 'model', '?')} از فهرست مدخل‌ها پاسخ متنی ساخت",
            "ms": round((_t.perf_counter() - _s) * 1000),
        })
    return {"intent": "analytics", "stats": stats, "summary": summary, "steps": steps}


async def commit_entry(
    session: AsyncSession, draft: dict, raw_text: str, *, source: str,
    related: list[dict] | None = None,
) -> Entry:
    doc, _status = await ingest_document(
        session,
        text=raw_text,
        source=source,
        title=draft.get("title") or None,
        metadata={
            "via": "assistant", "kind": draft.get("kind", "session"),
            **({"collection": draft["_collection"]} if draft.get("_collection") else {}),
            **{k: v for k, v in {
                "case_number": (draft.get("entities") or {}).get("case_number"),
                "case_type": (draft.get("entities") or {}).get("case_type"),
                "insurance_line": (draft.get("entities") or {}).get("insurance_line"),
                "group": (draft.get("entities") or {}).get("group"),
            }.items() if v},
        },
        replace=True,
    )

    # `related` comes from the pipeline's «پرونده‌های مشابه» gate (records the
    # user kept, with a score and a past outcome). Old callers pass nothing, so
    # fall back to a fresh semantic lookup for them.
    if related is None:
        found = await find_related(session, raw_text, exclude_source=source)
        related = [
            {"entry_id": None, "document_id": r["document_id"], "title": r["title"],
             "score": r.get("similarity"), "outcome": ""}
            for r in found
        ]
    related_ids = [r["document_id"] for r in related if r.get("document_id")]

    tags = [str(t).strip() for t in (draft.get("tags") or []) if str(t).strip()]

    from app.rag import casebase, lawbase

    refs = draft.get("legal_refs") or []
    if any(not r.get("ref_id") for r in refs if isinstance(r, dict)):
        refs = await lawbase.resolve_refs(session, refs, create_stubs=True)

    entry = Entry(
        document_id=doc.id if doc else None,
        kind=draft.get("kind", "session"),
        title=draft.get("title") or (raw_text.strip().splitlines()[0][:120] if raw_text.strip() else source),
        summary=draft.get("summary", ""),
        parties=draft.get("parties", []),
        representation=draft.get("representation", []),
        events=draft.get("events", []),
        entities=draft.get("entities", {}),
        tags=tags,
        related_ids=related_ids,
        related=related,
        legal_refs=refs,
        raw_text=raw_text,
    )
    session.add(entry)
    await session.flush()  # need entry.id for the label rows

    # The relational + graph side: case row, persons/orgs, citations, edges.
    await casebase.sync_entry(session, entry)

    # The user-curated label set is also written as Label rows so the taxonomy
    # view and the tag filters pick them up, not just the JSON column.
    for tag in tags:
        session.add(Label(
            kind="tag", target_type="entry", target_id=str(entry.id),
            value=tag, labeled_by="pipeline",
        ))

    from app.rag import hooks

    queued = await hooks.emit(session, "entry.committed", {
        "entry_id": str(entry.id), "title": entry.title, "source": source,
        "case_number": (entry.entities or {}).get("case_number"),
        "case_id": str(entry.case_id) if entry.case_id else None,
        "document_id": str(entry.document_id) if entry.document_id else None,
        "tags": tags, "legal_refs": len(refs),
    })
    await session.commit()
    await session.refresh(entry)
    if queued:
        hooks.drain_soon(session)
    return entry

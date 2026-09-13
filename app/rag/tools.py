"""
The read-only tools the model may call, and the loop that runs them.

Only lookups are exposed. `commit_entry` and everything else that writes stays
behind the pipeline's human gate (`app/rag/workflow.py`).

Two things changed in v3:

- **Evidence is numbered once.** Every tool result that carries a citable
  record (an article, a case, an entry, a document) goes through one
  `EvidenceLedger`, which assigns it a stable `[n]` and renders it the same
  way whichever tool found it. The model cites those numbers; the provenance
  check (`app/rag/provenance.py`) verifies them.
- **The loop is a transcript.** Rounds are kept as a neutral message list and
  sent through `LLMProvider.chat()`. Providers with native tool-result turns
  (Anthropic, OpenAI, Groq) replay them as such; everyone else gets the same
  transcript flattened to text — the shape the old loop always sent — so the
  offline `mock` model and small local models keep working unchanged.
"""

import json
import os
import time
from dataclasses import dataclass, field
from typing import AsyncIterator, Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.base import LLMProvider, LLMResponse, flatten_transcript
from app.llm.meter import usage_of


@dataclass
class Tool:
    name: str
    description: str          # Persian — shown to the model and in the log
    parameters: dict          # JSON schema; optional params are nullable
    handler: Callable[..., Awaitable[dict]]  # async (session, llm, **args) -> dict
    strict: bool = True       # send as a strict tool where the provider supports it
    evidence: Callable[[dict], list[dict]] | None = None  # result -> citable items
    max_chars: int = 1400     # cap on the JSON tail the model sees per result


@dataclass
class ToolLoopResult:
    text: str
    tool_log: list[dict] = field(default_factory=list)  # [{seq, tool, args, summary, ms, evidence_ns, error}]
    rounds: int = 0
    model: str = ""
    evidence: list[dict] = field(default_factory=list)  # the ledger's items
    usage: dict = field(default_factory=dict)           # summed over rounds
    transcript: list[dict] = field(default_factory=list)
    responses: list[LLMResponse] = field(default_factory=list)
    reasoning: str | None = None
    mode: str = "native"


# --------------------------------------------------------------------------- #
# Evidence ledger — one [n] sequence across every tool and every round
# --------------------------------------------------------------------------- #
_KIND_FA = {"law": "ماده", "case": "پرونده", "entry": "مدخل", "document": "سند"}


class EvidenceLedger:
    def __init__(self, items: list[dict] | None = None):
        self.items: list[dict] = []
        self._index: dict[tuple[str, str], int] = {}
        for item in items or []:
            self.add(**{k: v for k, v in item.items() if k != "n"})

    def add(self, kind: str, id: str, title: str = "", text: str = "", *,  # noqa: A002
            cite: str | None = None, case_number: str | None = None,
            score: float | None = None, tool: str | None = None,
            call_id: str | None = None, **extra) -> int:
        key = (kind, str(id))
        if key in self._index:
            return self._index[key]
        n = len(self.items) + 1
        self.items.append({
            "n": n, "kind": kind, "id": str(id), "title": title or cite or str(id),
            "cite": cite, "case_number": case_number, "score": score,
            "text": (text or "")[:600], "tool": tool, "call_id": call_id, **extra,
        })
        self._index[key] = n
        return n

    def get(self, n: int) -> dict | None:
        return self.items[n - 1] if 0 < n <= len(self.items) else None

    def render(self, ns: list[int] | None = None) -> str:
        """The numbered lines the model reads: `[n] (kind) cite — title\\ntext`."""
        rows = [self.items[n - 1] for n in (ns or range(1, len(self.items) + 1)) if 0 < n <= len(self.items)]
        lines = []
        for item in rows:
            head = f"[{item['n']}] ({_KIND_FA.get(item['kind'], item['kind'])}) "
            head += item["cite"] or item["title"] or ""
            if item["cite"] and item["title"] and item["title"] != item["cite"]:
                head += f" — {item['title']}"
            lines.append(head + (f"\n{item['text']}" if item["text"] else ""))
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Handlers — all take (session, llm, **args); ignore what they don't need
# --------------------------------------------------------------------------- #
async def _search_entries(session, llm, *, query: str = "", limit: int | None = 8, **_) -> dict:
    from app.rag.catalog import search_entries

    rows = await search_entries(session, query, limit=min(int(limit or 8), 15))
    return {"entries": [
        {
            "id": str(e.id),
            "document_id": str(e.document_id) if e.document_id else None,
            "title": e.title, "summary": (e.summary or "")[:240],
            "case_number": (e.entities or {}).get("case_number", ""),
            "tags": e.tags or [],
        }
        for e in rows
    ]}


async def _find_related(session, llm, *, text: str = "", top_k: int | None = 5, **_) -> dict:
    from app.rag.orchestrator import find_related

    return {"related": await find_related(session, text, top_k=min(int(top_k or 5), 10))}


async def _get_document(session, llm, *, document_id: str = "", **_) -> dict:
    from app.rag.ingest import get_document

    doc = await get_document(session, document_id)
    if not doc:
        return {"error": "سند یافت نشد"}
    return {
        "id": doc["id"], "title": doc["title"], "source": doc["source"],
        "raw_text": (doc["raw_text"] or "")[:4000],
    }


async def _corpus_stats(session, llm, **_) -> dict:
    from app.rag.orchestrator import corpus_stats

    stats = await corpus_stats(session)
    # trim the long top-N lists for the model's context
    return {
        "documents": stats["documents"], "chunks": stats["chunks"],
        "entries": stats["entries"],
        "top_topics": [t["name"] for t in stats["topics"][:8]],
        "top_people": [p["name"] for p in stats["people"][:8]],
        "top_lawyers": [l["name"] for l in stats["lawyers"][:8]],
    }


async def _search_law(session, llm, *, query: str = "", limit: int | None = 6, **_) -> dict:
    from app.rag.lawbase import search_laws

    rows = await search_laws(session, query, limit=min(int(limit or 6), 12))
    return {"articles": [
        {"id": r["id"], "cite": r["cite"], "title": r["title"], "text": (r["text"] or "")[:600]}
        for r in rows
    ]}


async def _search_cases(session, llm, *, query: str = "", limit: int | None = 6, **_) -> dict:
    from app.rag.casebase import search_cases

    rows = await search_cases(session, query, limit=min(int(limit or 6), 12))
    return {"cases": [
        {"id": r["id"], "case_number": r["case_number"], "title": r["title"],
         "case_type": r["case_type"], "insurance_line": r["insurance_line"],
         "court": r["court"], "status": r["status_fa"], "outcome": (r["outcome"] or "")[:200]}
        for r in rows
    ]}


async def _entity_profile(session, llm, *, name: str = "", kind: str | None = "person", **_) -> dict:
    from app.rag.casebase import entity_profile

    kind = "org" if kind in ("org", "organization", "company") else "person"
    prof = await entity_profile(session, kind, name)
    if not prof:
        other = "person" if kind == "org" else "org"
        prof = await entity_profile(session, other, name)
    if not prof:
        return {"error": "شخص یا سازمانی با این نام در بایگانی نیست"}
    return {
        "name": prof["name"], "type": prof["type"], "roles": prof["roles_fa"],
        "case_count": prof["case_count"],
        "cases": [
            {"id": c.get("id"), "case_number": c["case_number"], "title": c["title"], "role": c["role_fa"],
             "case_type": c["case_type"], "outcome": (c["outcome"] or "")[:160]}
            for c in prof["cases"][:12]
        ],
        "represents": [r["name"] for r in prof["represents"][:10]],
    }


async def _case_graph(session, llm, *, case_number: str = "", **_) -> dict:
    from app.rag import graph
    from app.rag.casebase import get_case

    case = await get_case(session, case_number)
    if not case:
        return {"error": "پرونده یافت نشد"}
    g = await graph.neighborhood(session, "case", case["id"], depth=1)
    return {
        "id": case["id"], "case_number": case["case_number"], "title": case["title"],
        "parties": [f"{p['name']} ({p['role_fa']})" for p in case["parties"]],
        "references": [r["cite"] + (f" — {r['context']}" if r.get("context") else "") for r in case["references"]],
        "outcome": case["outcome"], "nodes": len(g["nodes"]), "edges": len(g["edges"]),
        "neighbours": [
            {"type": n["type"], "id": n["id"], "label": n.get("label", "")}
            for n in g["nodes"] if not n.get("root")
        ][:40],
    }


async def _graph_expand(session, llm, *, node_type: str = "case", node_id: str = "",
                        depth: int | None = 2, **_) -> dict:
    """Cases connected to a node through shared articles, parties, courts or
    labels — the graph-walk half of «پرونده‌های مشابه». Filled in by
    `app/rag/similar.py`; until then the plain neighbourhood is returned."""
    from app.rag import graph

    try:
        from app.rag.similar import expand_for_tool
    except ImportError:  # phase 3 not present yet
        expand_for_tool = None
    if expand_for_tool is not None:
        return await expand_for_tool(session, node_type, node_id, depth=min(int(depth or 2), 3))
    g = await graph.neighborhood(session, node_type, node_id, depth=min(int(depth or 2), 3))
    return {"root": g["root"], "nodes": len(g["nodes"]), "edges": len(g["edges"]),
            "neighbours": [{"type": n["type"], "id": n["id"], "label": n.get("label", "")}
                           for n in g["nodes"] if not n.get("root")][:40]}


async def _similar_cases(session, llm, *, question: str = "", case_number: str | None = None,
                         limit: int | None = 5, **_) -> dict:
    """Resembling past cases with the reason for each link. Backed by
    `app/rag/similar.py`; falls back to the case-table search until then."""
    try:
        from app.rag.similar import similar_cases
    except ImportError:
        similar_cases = None
    if similar_cases is None:
        return await _search_cases(session, llm, query=question or case_number or "", limit=limit)
    items = await similar_cases(session, question=question, anchor_case_number=case_number,
                                top_k=min(int(limit or 5), 10))
    return {"cases": [
        {"id": c["id"], "case_number": c["case_number"], "title": c["title"],
         "case_type": c.get("case_type"), "insurance_line": c.get("insurance_line"),
         "court": c.get("court"), "status": c.get("status_fa"), "outcome": (c.get("outcome") or "")[:200],
         "score": c.get("score"), "why": c.get("why", [])}
        for c in items
    ]}


# --------------------------------------------------------------------------- #
# Evidence mappers — what in a result is citable
# --------------------------------------------------------------------------- #
def _ev_articles(out: dict) -> list[dict]:
    return [{"kind": "law", "id": a["id"], "title": a.get("title") or "", "cite": a.get("cite"),
             "text": a.get("text") or ""} for a in out.get("articles", [])]


def _ev_cases(out: dict) -> list[dict]:
    items = []
    for c in out.get("cases", []):
        text = " | ".join(str(v) for v in (c.get("case_type"), c.get("insurance_line"),
                                             c.get("court"), c.get("status")) if v)
        if c.get("outcome"):
            text += f"\nنتیجه: {c['outcome']}"
        if c.get("why"):
            text += "\nعلت شباهت: " + "؛ ".join(c["why"])
        items.append({"kind": "case", "id": c.get("id") or c.get("case_number"),
                      "title": c.get("title") or "", "cite": c.get("case_number"),
                      "case_number": c.get("case_number"), "score": c.get("score"), "text": text})
    return items


def _ev_entries(out: dict) -> list[dict]:
    return [{"kind": "entry", "id": e["id"], "title": e.get("title") or "", "cite": e.get("case_number") or None,
             "case_number": e.get("case_number"), "text": e.get("summary") or ""}
            for e in out.get("entries", [])]


def _ev_related(out: dict) -> list[dict]:
    return [{"kind": "document", "id": r.get("document_id") or r.get("title"), "title": r.get("title") or "",
             "score": r.get("similarity"), "text": r.get("snippet") or r.get("summary") or ""}
            for r in out.get("related", []) if r.get("document_id") or r.get("title")]


def _ev_document(out: dict) -> list[dict]:
    if "id" not in out:
        return []
    return [{"kind": "document", "id": out["id"], "title": out.get("title") or out.get("source") or "",
             "text": (out.get("raw_text") or "")[:600]}]


def _ev_profile(out: dict) -> list[dict]:
    return [{"kind": "case", "id": c.get("id") or c.get("case_number"), "title": c.get("title") or "",
             "cite": c.get("case_number"), "case_number": c.get("case_number"),
             "text": f"{out.get('name', '')} — {c.get('role', '')}" + (f"\nنتیجه: {c['outcome']}" if c.get("outcome") else "")}
            for c in out.get("cases", [])]


def _ev_case_graph(out: dict) -> list[dict]:
    if "case_number" not in out:
        return []
    text = "طرفین: " + "، ".join(out.get("parties", [])[:6])
    if out.get("references"):
        text += "\nمستندات: " + "؛ ".join(out["references"][:6])
    if out.get("outcome"):
        text += f"\nنتیجه: {out['outcome']}"
    return [{"kind": "case", "id": out.get("id") or out["case_number"], "title": out.get("title") or "",
             "cite": out["case_number"], "case_number": out["case_number"], "text": text}]


_STR = {"type": "string"}
_OPT_INT = {"type": ["integer", "null"], "description": "اختیاری"}

async def _archive_query(session, llm, query: str, within: list | None = None) -> dict:
    """«پرسش از آرشیو»: count the archive by label, not retrieve from it."""
    from app.rag import archive_query

    result = await archive_query.run(session, llm, query, within=within or None)
    return {
        "count": result["count"],
        "labels": (result["facets"]["tags"] + result["facets"]["insurance_lines"]
                   + result["facets"]["case_types"]),
        "by_label": result["by_label"][:12],
        "by_status": result["by_status"],
        "by_line": result["by_line"][:8],
        "case_ids": result["case_ids"][:60],
        "answer": archive_query.summarise(result),
    }


# --------------------------------------------------------------------------- #
# Editing — the only tools that touch a record, and neither of them writes
# --------------------------------------------------------------------------- #
# The tool set is otherwise read-only by design: writes stay behind a human
# gate. These two keep that rule. They build a proposal — the current value
# beside the new one — and the chat shows it for confirmation; only the
# confirmation calls `entryedit.apply`. The model's job is to identify which
# entry and which field the user means, never to author the value.
async def _find_entry(session, llm, query: str, limit: int = 6, **_) -> dict:
    from app.rag import catalog

    rows = await catalog.search_entries(session, query, limit=min(int(limit or 6), 15))
    return {"entries": [
        {"id": str(r.get("id")), "title": r.get("title") or "",
         "case_number": (r.get("entities") or {}).get("case_number") or "",
         "summary": (r.get("summary") or "")[:200]}
        for r in rows
    ]}


async def _propose_edit(session, llm, entry_id: str, field: str, value=None, **_) -> dict:
    from app.rag import entryedit

    try:
        return {"proposal": await entryedit.propose_edit(session, entry_id, field, value)}
    except entryedit.EditError as error:
        return {"error": str(error)}


async def _propose_append(session, llm, entry_id: str, field: str, item=None, **_) -> dict:
    from app.rag import entryedit

    try:
        return {"proposal": await entryedit.propose_append(session, entry_id, field, item)}
    except entryedit.EditError as error:
        return {"error": str(error)}


TOOLS: list[Tool] = [
    Tool(
        "archive_query",
        "شمارش و دسته‌بندی آرشیو بر اساس برچسب‌ها: «چند پرونده دربارهٔ ... داریم»، "
        "«پرتکرارترین برچسب‌ها در رشتهٔ ...»، «از همان‌ها چند تا مختومه شده». "
        "برچسب‌های مرتبط را از واژگان واقعی آرشیو انتخاب و سپس در پایگاه داده "
        "می‌شمارد — نه جستجوی متنی. برای پالایش پاسخ قبلی، `within` را با "
        "شناسه‌های همان مجموعه بفرستید.",
        {"type": "object", "properties": {
            "query": {"type": "string", "description": "پرسش دربارهٔ ترکیب آرشیو"},
            "within": {"type": ["array", "null"], "items": {"type": "string"},
                       "description": "شناسهٔ پرونده‌های پاسخ قبلی، برای پالایش"},
        }, "required": ["query"]},
        _archive_query,
    ),
    Tool(
        "search_law",
        "جستجو در پایگاه قوانین: متن و مفاد مواد قانون بیمه، قانون شخص ثالث، تأمین اجتماعی، آیین‌نامه‌ها و آرای وحدت رویه.",
        {"type": "object", "properties": {
            "query": {"type": "string", "description": "موضوع یا شمارهٔ ماده، مثلاً «ماده ۳۰ قانون بیمه»"},
            "limit": _OPT_INT,
        }, "required": ["query"]},
        _search_law, evidence=_ev_articles,
    ),
    Tool(
        "search_cases",
        "جستجو در بایگانی پرونده‌ها (جدول ساختاریافته): نوع دعوا، رشتهٔ بیمه، مرجع، نتیجه.",
        {"type": "object", "properties": {"query": _STR, "limit": _OPT_INT}, "required": ["query"]},
        _search_cases, evidence=_ev_cases,
    ),
    Tool(
        "similar_cases",
        "پرونده‌های مشابه یک پرسش یا یک پرونده در بایگانی، با علت شباهت (مادهٔ مشترک، طرف مشترک، مرجع، نوع دعوا) و نتیجهٔ هر کدام.",
        {"type": "object", "properties": {
            "question": {"type": "string", "description": "موضوع یا شرح پرونده"},
            "case_number": {"type": ["string", "null"], "description": "اختیاری: شمارهٔ پروندهٔ مبنا"},
            "limit": _OPT_INT,
        }, "required": ["question"]},
        _similar_cases, evidence=_ev_cases,
    ),
    Tool(
        "entity_profile",
        "پروفایل یک شخص (وکیل، قاضی، طرف دعوا) یا سازمان (شرکت بیمه، بانک): همهٔ پرونده‌ها و نقش‌هایش.",
        {"type": "object", "properties": {
            "name": _STR,
            "kind": {"type": ["string", "null"], "enum": ["person", "org", None]},
        }, "required": ["name"]},
        _entity_profile, evidence=_ev_profile,
    ),
    Tool(
        "case_graph",
        "گراف یک پرونده با شمارهٔ آن: طرفین، وکلا، مواد قانونی استنادشده، مرجع و نتیجه.",
        {"type": "object", "properties": {"case_number": _STR}, "required": ["case_number"]},
        _case_graph, evidence=_ev_case_graph,
    ),
    Tool(
        "graph_expand",
        "گسترش گراف از یک گره (پرونده، ماده، شخص، سازمان): پرونده‌های متصل از طریق مواد، طرفین، مرجع و برچسب‌های مشترک.",
        {"type": "object", "properties": {
            "node_type": {"type": "string", "enum": ["case", "law", "person", "org", "entry"]},
            "node_id": {"type": "string", "description": "شناسه یا شمارهٔ پرونده / شناسهٔ ماده"},
            "depth": _OPT_INT,
        }, "required": ["node_type", "node_id"]},
        _graph_expand, evidence=_ev_cases,
    ),
    Tool(
        "search_entries",
        "جستجوی مدخل‌های ساختاریافتهٔ آرشیو با واژه‌های کلیدی (نام شخص، شمارهٔ پرونده، موضوع).",
        {"type": "object", "properties": {
            "query": {"type": "string", "description": "عبارت جستجو به فارسی"},
            "limit": _OPT_INT,
        }, "required": ["query"]},
        _search_entries, evidence=_ev_entries,
    ),
    Tool(
        "find_related",
        "یافتن اسناد مرتبط با یک متن از طریق جستجوی معنایی (نه کلیدواژه‌ای).",
        {"type": "object", "properties": {"text": _STR, "top_k": _OPT_INT}, "required": ["text"]},
        _find_related, evidence=_ev_related,
    ),
    Tool(
        "get_document",
        "متن کامل یک سند بر اساس شناسهٔ آن (document_id از نتایج ابزارهای دیگر).",
        {"type": "object", "properties": {"document_id": _STR}, "required": ["document_id"]},
        _get_document, evidence=_ev_document,
    ),
    Tool(
        "corpus_stats",
        "آمار کلی آرشیو: تعداد اسناد و مدخل‌ها، موضوعات و اشخاص پرتکرار.",
        {"type": "object", "properties": {}},
        _corpus_stats,
    ),
    Tool(
        "find_entry",
        "یافتن مدخل برای ویرایش: با عنوان، شمارهٔ پرونده یا موضوع جستجو می‌کند و "
        "شناسهٔ مدخل‌ها را برمی‌گرداند. پیش از هر ویرایش، مدخل را با این ابزار پیدا کنید.",
        {"type": "object", "properties": {
            "query": {"type": "string", "description": "عنوان، شمارهٔ پرونده یا موضوع مدخل"},
            "limit": _OPT_INT,
        }, "required": ["query"]},
        _find_entry,
    ),
    Tool(
        "propose_edit",
        "پیشنهاد تغییر یک فیلد از یک مدخل. چیزی را ذخیره نمی‌کند — مقدار فعلی و "
        "مقدار جدید را برای تأیید کاربر برمی‌گرداند. `value` باید دقیقاً همان چیزی "
        "باشد که کاربر گفته است؛ مقدار جدید را خودتان نسازید. فیلدها: عنوان، خلاصه، "
        "نوع، برچسب‌ها، شمارهٔ پرونده، مرجع رسیدگی، موضوع.",
        {"type": "object", "properties": {
            "entry_id": {"type": "string", "description": "شناسهٔ مدخل از find_entry"},
            "field": {"type": "string", "description": "نام فیلد، فارسی یا انگلیسی"},
            "value": {"type": "string", "description": "مقدار جدید، به بیان خود کاربر"},
        }, "required": ["entry_id", "field", "value"]},
        _propose_edit,
    ),
    Tool(
        "propose_append",
        "پیشنهاد افزودن یک مورد به فیلد فهرستی یک مدخل — مثلاً یک رویداد به تایم‌لاین "
        "یا یک برچسب. چیزی را ذخیره نمی‌کند. برای رویداد، تاریخ را در ابتدای متن "
        "بیاورید: «۱۴۰۳/۰۵/۱۲ جلسهٔ کارشناسی».",
        {"type": "object", "properties": {
            "entry_id": {"type": "string", "description": "شناسهٔ مدخل از find_entry"},
            "field": {"type": "string", "description": "رویدادها، برچسب‌ها، طرفین، وکالت یا مستندات قانونی"},
            "item": {"type": "string", "description": "موردی که اضافه می‌شود، به بیان خود کاربر"},
        }, "required": ["entry_id", "field", "item"]},
        _propose_append,
    ),
]
_BY_NAME = {t.name: t for t in TOOLS}


def tool_specs(tools: list[Tool] = TOOLS) -> list[dict]:
    return [
        {"name": t.name, "description": t.description, "parameters": t.parameters, "strict": t.strict}
        for t in tools
    ]


def _unwrap_args(args: dict) -> dict:
    """Some models (aya-expanse) wrap the real arguments in a `parameters` key
    and add `tool_name`/`name` alongside — unwrap to the flat call arguments."""
    if not isinstance(args, dict):
        return {}
    inner = args.get("parameters")
    if isinstance(inner, dict) and set(args) <= {"parameters", "tool_name", "name", "arguments"}:
        return inner
    return {k: v for k, v in args.items() if k not in ("tool_name",)}


def _fmt_args(args: dict) -> str:
    return ", ".join(f"{k}={v!r}" for k, v in (args or {}).items())


def _summarise(name: str, args: dict, out: dict) -> str:
    if "error" in out:
        return f"{name}({_fmt_args(args)}) → خطا: {out['error']}"
    if name == "search_entries":
        return f"search_entries({_fmt_args(args)}) → {len(out.get('entries', []))} مدخل"
    if name == "find_related":
        return f"find_related({_fmt_args(args)}) → {len(out.get('related', []))} سند"
    if name == "get_document":
        return f"get_document({_fmt_args(args)}) → «{out.get('title', '')}»"
    if name == "corpus_stats":
        return f"corpus_stats → {out.get('entries', 0)} مدخل، {out.get('documents', 0)} سند"
    if name == "search_law":
        return f"search_law({_fmt_args(args)}) → {len(out.get('articles', []))} ماده"
    if name in ("search_cases", "similar_cases", "graph_expand"):
        return f"{name}({_fmt_args(args)}) → {len(out.get('cases', []))} پرونده"
    if name == "entity_profile":
        return f"entity_profile({_fmt_args(args)}) → {out.get('case_count', 0)} پرونده"
    if name == "case_graph":
        return f"case_graph({_fmt_args(args)}) → {out.get('nodes', 0)} گره، {out.get('edges', 0)} یال"
    return f"{name}({_fmt_args(args)})"


def loop_mode(llm: LLMProvider) -> str:
    """`native` when the provider replays tool results itself and TOOL_LOOP
    does not force the text loop; `text` otherwise."""
    wanted = os.environ.get("TOOL_LOOP", "native").strip().lower()
    if wanted == "text" or not getattr(llm, "supports_native_tools", False):
        return "text"
    return "native"


def _use_cache(llm: LLMProvider) -> bool:
    return os.environ.get("PROMPT_CACHE", "1") == "1" and bool(getattr(llm, "supports_prompt_cache", False))


async def _execute(session, llm, call: dict, ledger: EvidenceLedger, done: set[str], seq: int,
                   by_name: dict[str, Tool] | None = None) -> tuple[dict, str, bool]:
    """Run one call. Returns (log row, content for the model, is_error)."""
    by_name = by_name or _BY_NAME
    name = call.get("name", "")
    args = _unwrap_args(call.get("arguments") or {})
    tool = by_name.get(name)
    if tool is None:
        row = {"seq": seq, "tool": name, "args": args, "summary": f"{name}: ابزار ناشناخته",
               "ms": 0, "evidence_ns": [], "error": "unknown tool"}
        return row, f"[{name}: ابزار ناشناخته — ابزارهای مجاز: {', '.join(by_name)}]", True

    fingerprint = f"{name}:{json.dumps(args, sort_keys=True, ensure_ascii=False)}"
    if fingerprint in done:
        row = {"seq": seq, "tool": name, "args": args, "summary": f"{name}({_fmt_args(args)}) → قبلاً اجرا شد",
               "ms": 0, "evidence_ns": [], "error": None, "repeat": True}
        return row, "این فراخوانی قبلاً اجرا شده است؛ نتیجهٔ آن در بالا آمده — از همان استفاده کن.", False
    done.add(fingerprint)

    t0 = time.perf_counter()
    try:
        out = await tool.handler(session, llm, **args)
    except Exception as error:  # noqa: BLE001 — surfaced to the model + log
        out = {"error": f"{type(error).__name__}: {error}"}
    ms = round((time.perf_counter() - t0) * 1000)

    evidence_ns: list[int] = []
    if tool.evidence and "error" not in out:
        for item in tool.evidence(out):
            if not item.get("id"):
                continue
            n = ledger.add(tool=name, call_id=call.get("id"), **item)
            if n not in evidence_ns:
                evidence_ns.append(n)

    content = json.dumps(out, ensure_ascii=False)[:tool.max_chars]
    if evidence_ns:
        content = "شواهد شماره‌گذاری‌شده (برای استناد از همین شماره‌ها استفاده کن):\n" \
                  + ledger.render(evidence_ns) + "\n\n" + content
    row = {"seq": seq, "tool": name, "args": args, "summary": _summarise(name, args, out),
           "ms": ms, "evidence_ns": evidence_ns, "error": out.get("error")}
    return row, content, "error" in out


async def iter_with_tools(
    llm: LLMProvider, session: AsyncSession, prompt: str, *, system: str,
    tools: list[Tool] = TOOLS, max_rounds: int = 4, max_tokens: int = 800,
    ledger: EvidenceLedger | None = None, reasoning_effort: str | None = "low",
    mode: str | None = None, cache: bool | None = None,
) -> AsyncIterator[dict]:
    """generate → dispatch → feed results back → generate, as a stream of events:

        {"type": "round",       "round": n}
        {"type": "tool_call",   "round": n, "tool", "args"}
        {"type": "tool_result", "round": n, "tool", "summary", "ms", "evidence_ns", "error"}
        {"type": "answer",      "text", "response"}
        {"type": "done",        "result": ToolLoopResult}
    """
    ledger = ledger if ledger is not None else EvidenceLedger()
    mode = mode or loop_mode(llm)
    cache = _use_cache(llm) if cache is None else cache
    specs = tool_specs(tools)
    by_name = {t.name: t for t in tools}
    messages: list[dict] = [{"role": "user", "content": prompt}]
    log: list[dict] = []
    responses: list[LLMResponse] = []
    done: set[str] = set()  # (name, args) already run — small models repeat themselves
    model = ""

    async def call_model(tool_choice: str) -> LLMResponse:
        if mode == "native":
            return await llm.chat(
                messages, system=system, tools=specs, tool_choice=tool_choice,
                max_tokens=max_tokens, reasoning_effort=reasoning_effort, cache=cache,
            )
        return await llm.generate(
            flatten_transcript(messages), system=system,
            tools=None if tool_choice == "none" else specs,
            max_tokens=max_tokens, reasoning_effort=reasoning_effort,
        )

    def finish(resp: LLMResponse, rounds: int) -> ToolLoopResult:
        return ToolLoopResult(
            text=resp.text, tool_log=log, rounds=rounds, model=model or resp.model,
            evidence=list(ledger.items), usage=usage_of(responses), transcript=list(messages),
            responses=list(responses), reasoning=resp.reasoning, mode=mode,
        )

    for rnd in range(1, max_rounds + 1):
        yield {"type": "round", "round": rnd}
        resp = await call_model("auto")
        responses.append(resp)
        model = resp.model or model
        messages.append({"role": "assistant", "content": resp.text,
                         "tool_calls": resp.tool_calls, "turn": resp.turn})
        if not resp.tool_calls:
            yield {"type": "answer", "text": resp.text, "response": resp}
            yield {"type": "done", "result": finish(resp, rnd)}
            return

        for call in resp.tool_calls:
            yield {"type": "tool_call", "round": rnd, "tool": call.get("name"),
                   "args": _unwrap_args(call.get("arguments") or {})}
            row, content, is_error = await _execute(session, llm, call, ledger, done, len(log) + 1, by_name)
            log.append(row)
            messages.append({"role": "tool", "tool_call_id": str(call.get("id") or f"call_{len(log)}"),
                             "name": call.get("name", ""), "content": content, "is_error": is_error})
            yield {"type": "tool_result", "round": rnd, **row}

    messages.append({"role": "user", "content": "Now answer directly, without calling any more tools."})
    resp = await call_model("none")
    responses.append(resp)
    messages.append({"role": "assistant", "content": resp.text, "tool_calls": None, "turn": resp.turn})
    yield {"type": "answer", "text": resp.text, "response": resp}
    yield {"type": "done", "result": finish(resp, max_rounds)}


async def run_with_tools(
    llm: LLMProvider, session: AsyncSession, prompt: str, *, system: str,
    tools: list[Tool] = TOOLS, max_rounds: int = 4, max_tokens: int = 800,
    ledger: EvidenceLedger | None = None, **options,
) -> ToolLoopResult:
    """The loop as one call — what the pipeline's «similar» step and the API use."""
    result: ToolLoopResult | None = None
    async for event in iter_with_tools(
        llm, session, prompt, system=system, tools=tools, max_rounds=max_rounds,
        max_tokens=max_tokens, ledger=ledger, **options,
    ):
        if event["type"] == "done":
            result = event["result"]
    assert result is not None
    return result

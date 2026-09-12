"""
The read-only tools the model may call, and the loop that runs them.

Only lookups are exposed. `commit_entry` and everything else that writes stays
behind the pipeline's human gate (`app/rag/workflow.py`). The loop feeds each
tool result back as plain text rather than as formal tool-role messages, so it
works with any provider that fills in `LLMResponse.tool_calls` — local Ollama
models included — without a multi-turn `chat()` method on the provider.
"""

import json
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.base import LLMProvider


@dataclass
class Tool:
    name: str
    description: str          # Persian — shown to the model and in the log
    parameters: dict          # JSON schema
    handler: Callable[..., Awaitable[dict]]  # async (session, llm, **args) -> dict


@dataclass
class ToolLoopResult:
    text: str
    tool_log: list[dict] = field(default_factory=list)  # [{tool, args, summary}]
    rounds: int = 0
    model: str = ""


# --------------------------------------------------------------------------- #
# Handlers — all take (session, llm, **args); ignore what they don't need
# --------------------------------------------------------------------------- #
async def _search_entries(session, llm, *, query: str = "", limit: int = 8, **_) -> dict:
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


async def _find_related(session, llm, *, text: str = "", top_k: int = 5, **_) -> dict:
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


async def _search_law(session, llm, *, query: str = "", limit: int = 6, **_) -> dict:
    from app.rag.lawbase import search_laws

    rows = await search_laws(session, query, limit=min(int(limit or 6), 12))
    return {"articles": [
        {"id": r["id"], "cite": r["cite"], "title": r["title"], "text": (r["text"] or "")[:600]}
        for r in rows
    ]}


async def _search_cases(session, llm, *, query: str = "", limit: int = 6, **_) -> dict:
    from app.rag.casebase import search_cases

    rows = await search_cases(session, query, limit=min(int(limit or 6), 12))
    return {"cases": [
        {"id": r["id"], "case_number": r["case_number"], "title": r["title"],
         "case_type": r["case_type"], "insurance_line": r["insurance_line"],
         "court": r["court"], "status": r["status_fa"], "outcome": (r["outcome"] or "")[:200]}
        for r in rows
    ]}


async def _entity_profile(session, llm, *, name: str = "", kind: str = "person", **_) -> dict:
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
            {"case_number": c["case_number"], "title": c["title"], "role": c["role_fa"],
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
        "case_number": case["case_number"], "title": case["title"],
        "parties": [f"{p['name']} ({p['role_fa']})" for p in case["parties"]],
        "references": [r["cite"] + (f" — {r['context']}" if r.get("context") else "") for r in case["references"]],
        "outcome": case["outcome"], "nodes": len(g["nodes"]), "edges": len(g["edges"]),
    }


TOOLS: list[Tool] = [
    Tool(
        "search_law",
        "جستجو در پایگاه قوانین: متن و مفاد مواد قانون بیمه، قانون شخص ثالث، تأمین اجتماعی، آیین‌نامه‌ها و آرای وحدت رویه.",
        {"type": "object", "properties": {
            "query": {"type": "string", "description": "موضوع یا شمارهٔ ماده، مثلاً «ماده ۳۰ قانون بیمه»"},
            "limit": {"type": "integer"},
        }, "required": ["query"]},
        _search_law,
    ),
    Tool(
        "search_cases",
        "جستجو در بایگانی پرونده‌ها (جدول ساختاریافته): نوع دعوا، رشتهٔ بیمه، مرجع، نتیجه.",
        {"type": "object", "properties": {
            "query": {"type": "string"}, "limit": {"type": "integer"},
        }, "required": ["query"]},
        _search_cases,
    ),
    Tool(
        "entity_profile",
        "پروفایل یک شخص (وکیل، قاضی، طرف دعوا) یا سازمان (شرکت بیمه، بانک): همهٔ پرونده‌ها و نقش‌هایش.",
        {"type": "object", "properties": {
            "name": {"type": "string"},
            "kind": {"type": "string", "enum": ["person", "org"]},
        }, "required": ["name"]},
        _entity_profile,
    ),
    Tool(
        "case_graph",
        "گراف یک پرونده با شمارهٔ آن: طرفین، وکلا، مواد قانونی استنادشده، مرجع و نتیجه.",
        {"type": "object", "properties": {"case_number": {"type": "string"}}, "required": ["case_number"]},
        _case_graph,
    ),
    Tool(
        "search_entries",
        "جستجوی مدخل‌های ساختاریافتهٔ آرشیو با واژه‌های کلیدی (نام شخص، شمارهٔ پرونده، موضوع).",
        {"type": "object", "properties": {
            "query": {"type": "string", "description": "عبارت جستجو به فارسی"},
            "limit": {"type": "integer"},
        }, "required": ["query"]},
        _search_entries,
    ),
    Tool(
        "find_related",
        "یافتن اسناد مرتبط با یک متن از طریق جستجوی معنایی (نه کلیدواژه‌ای).",
        {"type": "object", "properties": {
            "text": {"type": "string"}, "top_k": {"type": "integer"},
        }, "required": ["text"]},
        _find_related,
    ),
    Tool(
        "get_document",
        "متن کامل یک سند بر اساس شناسهٔ آن (document_id از نتایج ابزارهای دیگر).",
        {"type": "object", "properties": {
            "document_id": {"type": "string"},
        }, "required": ["document_id"]},
        _get_document,
    ),
    Tool(
        "corpus_stats",
        "آمار کلی آرشیو: تعداد اسناد و مدخل‌ها، موضوعات و اشخاص پرتکرار.",
        {"type": "object", "properties": {}},
        _corpus_stats,
    ),
]
_BY_NAME = {t.name: t for t in TOOLS}


def tool_specs(tools: list[Tool] = TOOLS) -> list[dict]:
    return [
        {"name": t.name, "description": t.description, "parameters": t.parameters}
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
    if name == "search_cases":
        return f"search_cases({_fmt_args(args)}) → {len(out.get('cases', []))} پرونده"
    if name == "entity_profile":
        return f"entity_profile({_fmt_args(args)}) → {out.get('case_count', 0)} پرونده"
    if name == "case_graph":
        return f"case_graph({_fmt_args(args)}) → {out.get('nodes', 0)} گره، {out.get('edges', 0)} یال"
    return f"{name}({_fmt_args(args)})"


async def run_with_tools(
    llm: LLMProvider, session: AsyncSession, prompt: str, *, system: str,
    tools: list[Tool] = TOOLS, max_rounds: int = 4, max_tokens: int = 800,
) -> ToolLoopResult:
    """generate → dispatch → feed results back → generate, up to `max_rounds`."""
    specs = tool_specs(tools)
    convo = prompt
    log: list[dict] = []
    model = ""
    done: set[str] = set()  # (name, args) already run — small models repeat themselves

    for rnd in range(1, max_rounds + 1):
        resp = await llm.generate(
            convo, system=system, tools=specs, max_tokens=max_tokens,
            reasoning_effort="low",
        )
        model = resp.model or model
        if not resp.tool_calls:
            return ToolLoopResult(text=resp.text, tool_log=log, rounds=rnd, model=model)

        chunks: list[str] = []
        for call in resp.tool_calls:
            tool = _BY_NAME.get(call["name"])
            args = _unwrap_args(call.get("arguments") or {})
            if tool is None:
                chunks.append(f"[{call['name']}: ابزار ناشناخته]")
                continue
            fingerprint = f"{call['name']}:{json.dumps(args, sort_keys=True, ensure_ascii=False)}"
            if fingerprint in done:
                chunks.append(f"[{call['name']}({_fmt_args(args)}) → قبلاً اجرا شد]")
                continue
            done.add(fingerprint)
            try:
                out = await tool.handler(session, llm, **args)
            except Exception as error:  # noqa: BLE001 — surfaced to the model + log
                out = {"error": f"{type(error).__name__}: {error}"}
            log.append({"tool": call["name"], "args": args, "summary": _summarise(call["name"], args, out)})
            chunks.append(
                f"[{call['name']}({_fmt_args(args)}) → "
                f"{json.dumps(out, ensure_ascii=False)[:1400]}]"
            )

        convo = (
            f"{convo}\n\nYou called tools and received:\n" + "\n".join(chunks)
            + "\n\nUse these results. Call another tool only if you still need one."
        )

    resp = await llm.generate(
        convo + "\n\nNow answer directly, without calling any more tools.",
        system=system, max_tokens=max_tokens,
    )
    return ToolLoopResult(text=resp.text, tool_log=log, rounds=max_rounds, model=model or resp.model)

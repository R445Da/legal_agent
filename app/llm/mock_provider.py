"""
A deterministic, offline "model" for demos and tests: `LLM_PROVIDER=mock`.

It never calls a network. It recognises the three prompt shapes the system
sends — the router, the extractor, and an answer over numbered excerpts — and
produces plausible, rule-based output for each, so the whole pipeline
(routing → extraction → references gate → commit → graph) can be walked with
no API key. Answers are honest about what they are: a rule-based summary of the
retrieved evidence, cited as [n], not reasoning.

Swap to a real model by setting LLM_PROVIDER / LLM_MODEL in .env — nothing
else changes.
"""

from __future__ import annotations

import json
import re
import time

from .base import LLMProvider, LLMResponse

_ARTICLE = re.compile(r"(?:ماد[هۀ]|تبصر[هۀ])\s*([0-9۰-۹]+)\s*(?:از\s+)?((?:قانون|آیین‌نامه|آیین نامه|رأی وحدت رویه|رای وحدت رویه)(?:\s+\S+){0,7})")
_LAW_STOP = {"استناد", "کرد", "کردند", "نمود", "شد", "مورد", "بحث", "همچنین", "که", "را", "است", "بود", "با", "به",
             "در", "از", "بر", "طبق", "مطابق", "علیه", "قرار", "گرفت", "دادگاه", "خوانده", "خواهان", "بیمه‌گر", "مصوب"}


def _trim_law(title: str) -> str:
    """Cut the captured law name at the first verb/particle — «قانون بیمه استناد کرد» -> «قانون بیمه»."""
    out = []
    for word in title.split():
        w = word.strip("،؛.()")
        if w in _LAW_STOP or re.fullmatch(r"1[34][0-9]{2}|[۱][۳۴][۰-۹]{2}", w):
            if w in _LAW_STOP:
                break
            continue
        out.append(w)
    return " ".join(out)
_CASE_NO = re.compile(r"(?:کلاسه|شماره)\s*(?:پرونده)?\s*[:：]?\s*([0-9۰-۹/\-]{5,20})")
_COURT = re.compile(r"((?:دادگاه|شورای حل اختلاف|دیوان عدالت اداری|هیئت|هیأت|دادسرا)[^\n،؛]{2,80})")
_ROLE_RX = [
    ("khahan", re.compile(r"خواهان\s*[:：]\s*([^\n\(]+)")),
    ("khande", re.compile(r"خوانده\s*[:：]\s*([^\n\(]+)")),
    ("shaki", re.compile(r"شاکی\s*[:：]\s*([^\n\(]+)")),
    ("mottaham", re.compile(r"متهم\s*[:：]\s*([^\n\(]+)")),
    ("ghazi", re.compile(r"قاضی\s*[:：]\s*([^\n\(]+)")),
]
_LAWYER_RX = re.compile(r"(خواهان|خوانده|شاکی|متهم)\s*[:：]\s*([^\n\(]+?)\s*\(با وکالت\s+([^\)]+)\)")
_DATE = re.compile(r"(1[34][0-9]{2}/[0-9]{2}/[0-9]{2}|[۱][۳۴][۰-۹]{2}/[۰-۹]{2}/[۰-۹]{2})")
_FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")


def _digits(s: str) -> str:
    return (s or "").translate(_FA_DIGITS)


class MockProvider(LLMProvider):
    name = "mock"

    def __init__(self, model: str | None = None, **_):
        self.model = model or "rules-v1"

    def is_available(self) -> bool:
        return True

    # ------------------------------------------------------------------ #
    async def generate(self, prompt: str, *, system: str = "", max_tokens: int = 1024,
                       temperature: float = 0.0, json_mode: bool = False, tools=None,
                       tool_choice: str = "auto", **knobs) -> LLMResponse:
        t0 = time.perf_counter()
        sys_l = (system or "").lower()
        # The research agent: ask for the archive first, answer on the next
        # round — so the tool loop, the evidence ledger and the citation check
        # all run offline exactly as they would with a real model.
        if tools and "archive research agent" in sys_l and "you called tools and received" not in prompt.lower():
            calls = self._agent_calls(prompt, tools)
            return LLMResponse(text="", model=f"mock/{self.model}", tool_calls=calls or None,
                               stop_reason="tool_use" if calls else "end_turn",
                               input_tokens=len(prompt) // 4, output_tokens=0,
                               latency_ms=(time.perf_counter() - t0) * 1000)
        if "route a message" in sys_l:
            text = self._route(prompt)
        elif "extract structured data" in sys_l:
            text = self._extract(prompt)
        elif "propose" in sys_l and "label" in sys_l:
            text = json.dumps({"labels": []}, ensure_ascii=False)
        elif "merge a user's reply" in sys_l:
            text = self._merge(prompt)
        else:
            text = self._answer(prompt, system or "")
        return LLMResponse(text=text, model=f"mock/{self.model}", input_tokens=len(prompt) // 4,
                           output_tokens=len(text) // 4, latency_ms=(time.perf_counter() - t0) * 1000)

    # ------------------------------------------------------------------ #
    @staticmethod
    def _agent_calls(prompt: str, tools) -> list[dict]:
        """One archive search, plus a statute search when an article is named."""
        offered = {t.get("name") for t in tools or []}
        question = prompt.split("Question:", 1)[-1].strip() if "Question:" in prompt else prompt.strip()
        question = question.splitlines()[0][:200] if question else ""
        calls = []
        if "search_cases" in offered:
            calls.append({"id": "call_1", "name": "search_cases", "arguments": {"query": question, "limit": 6}})
        if "search_law" in offered and re.search(r"(?:ماد[هۀ]|تبصر[هۀ])\s*[0-9۰-۹]+|قانون", question):
            calls.append({"id": "call_2", "name": "search_law", "arguments": {"query": question, "limit": 4}})
        return calls

    def _route(self, prompt: str) -> str:
        msg = prompt.split("Message:", 1)[-1].strip()
        q = any(m in msg for m in ("؟", "?", "چه ", "چیست", "کدام", "چطور", "چگونه", "آیا", "نشان بده"))
        if re.search(r"(?:ماد[هۀ]|تبصر[هۀ])\s*[0-9۰-۹]+", msg) or any(k in msg for k in ("طبق قانون", "قانون بیمه", "مرور زمان", "آیین‌نامه")) and q:
            return json.dumps({"intent": "law", "confidence": 0.9, "clarify": ""}, ensure_ascii=False)
        if any(k in msg for k in ("چند ", "تعداد", "آمار")):
            return json.dumps({"intent": "analytics", "confidence": 0.9, "clarify": ""}, ensure_ascii=False)
        if any(k in msg for k in ("پرونده‌های", "پرونده های", "سابقه", "رویه", "وکیل", "در چه پرونده")) and q:
            return json.dumps({"intent": "cases", "confidence": 0.85, "clarify": ""}, ensure_ascii=False)
        if q:
            return json.dumps({"intent": "query", "confidence": 0.8, "clarify": ""}, ensure_ascii=False)
        if len(msg) > 80 and any(k in msg for k in ("خواهان", "خوانده", "جلسه", "دادگاه", "رأی", "رای", "شاکی")):
            return json.dumps({"intent": "archive", "confidence": 0.88, "clarify": ""}, ensure_ascii=False)
        if len(msg) < 25:
            return json.dumps({"intent": "chat", "confidence": 0.7, "clarify": ""}, ensure_ascii=False)
        return json.dumps({"intent": "unclear", "confidence": 0.4,
                           "clarify": "منظورتان ثبت این مطلب است یا پرسشی درباره‌اش؟"}, ensure_ascii=False)

    def _extract(self, prompt: str) -> str:
        text = prompt.split("Text:", 1)[-1].strip()
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        title = lines[0][:120] if lines else "مدخل"
        parties, people, orgs = [], [], []
        for role, rx in _ROLE_RX:
            for m in rx.finditer(text):
                name = m.group(1).strip(" .،")
                parties.append({"name": name, "role": role})
        representation = []
        for m in _LAWYER_RX.finditer(text):
            lawyer = m.group(3).strip()
            representation.append({"lawyer": lawyer, "client": m.group(2).strip()})
            parties.append({"name": lawyer, "role": "vakil_khahan" if m.group(1) == "خواهان" else "vakil_khande"})
        for p in parties:
            (orgs if any(h in p["name"] for h in ("شرکت", "بیمه", "بانک", "سازمان", "صندوق")) else people).append(p["name"])
        refs = []
        for m in _ARTICLE.finditer(text):
            law = _trim_law(m.group(2))
            if law:
                refs.append({"law": law, "article": _digits(m.group(1)), "context": "", "used_by": "court"})
        seen, uniq = set(), []
        for r in refs:
            k = (r["law"], r["article"])
            if k not in seen:
                seen.add(k)
                uniq.append(r)
        case_no = _CASE_NO.search(text)
        court = _COURT.search(text)
        events = [{"date": _digits(d), "description": "رویداد ثبت‌شده در متن"} for d in dict.fromkeys(_DATE.findall(text))][:6]
        m_type = re.search(r"نوع دعوا\s*[:：]\s*([^\n—]+)", text)
        m_line = re.search(r"رشتهٔ? بیمه\s*[:：]\s*([^\n]+)", text)
        m_out = re.search(r"(?:رأی|رای) دادگاه\s*[:：]?\s*\n?([^\n]+)", text)
        m_amt = re.search(r"([0-9۰-۹,،]{6,})\s*ریال", text)
        summary = " ".join(lines[1:4])[:400] if len(lines) > 1 else title
        data = {
            "kind": "session", "title": title, "summary": summary,
            "parties": parties, "representation": representation, "events": events,
            "entities": {
                "people": list(dict.fromkeys(people)), "orgs": list(dict.fromkeys(orgs)),
                "case_number": _digits(case_no.group(1)) if case_no else "",
                "court": court.group(1).strip() if court else "",
                "topic": (re.search(r"موضوع\s*[:：]\s*([^\n]+)", text) or [None, ""])[1] if re.search(r"موضوع\s*[:：]", text) else title,
                "case_type": m_type.group(1).strip() if m_type else "",
                "insurance_line": m_line.group(1).strip() if m_line else "",
                "claim_amount": _digits(m_amt.group(1)).replace(",", "").replace("،", "") if m_amt else "",
                "outcome": m_out.group(1).strip() if m_out else "",
                "status": "closed" if m_out else "open", "filed_date": events[0]["date"] if events else "",
            },
            "legal_refs": uniq,
            "tags": [t for t in [m_line.group(1).strip() if m_line else "", "بیمه"] if t],
        }
        return json.dumps(data, ensure_ascii=False)

    def _merge(self, prompt: str) -> str:
        """Conversation mode: read labelled lines and a case number out of the
        user's reply — the same shape a real model returns for MERGE_SCHEMA."""
        reply = prompt.split("User reply:", 1)[-1].split("Respond with JSON only", 1)[0].strip()
        low = reply.lower()
        ent: dict = {}
        data: dict = {"title": None, "summary": None, "entities": ent,
                      "confirm": any(w in low for w in ("تأیید", "تایید", "ثبت کن", "درست است")) and len(reply) < 40,
                      "cancel": any(w in low for w in ("انصراف", "لغو")) and len(reply) < 40, "note": None}
        labels = {"عنوان": ("title", None), "خلاصه": ("summary", None), "مرجع": (None, "court"),
                  "دادگاه": (None, "court"), "نوع دعوا": (None, "case_type"), "رشته": (None, "insurance_line"),
                  "نتیجه": (None, "outcome"), "وضعیت": (None, "status")}
        for line in reply.splitlines():
            m = re.match(r"^\s*([^:：]{2,24}?)\s*[:：]\s*(.+?)\s*$", line)
            if not m:
                continue
            top, key = labels.get(m.group(1).strip(), (None, None))
            if top:
                data[top] = m.group(2)
            elif key:
                ent[key] = m.group(2)
        m = _CASE_NO.search(reply)
        if m:
            ent["case_number"] = _digits(m.group(1))
        return json.dumps(data, ensure_ascii=False)

    def _answer(self, prompt: str, system: str) -> str:
        """Rule-based: the question, then each numbered excerpt's first line, cited."""
        cites = re.findall(r"^\[(\d+)\]\s*(.+)$", prompt, flags=re.MULTILINE)
        q = re.search(r"Question:\s*(.+)", prompt)
        head = f"پاسخ (مدل آزمایشی — خلاصهٔ قاعده‌مند شواهد بازیابی‌شده){' برای: ' + q.group(1).strip() if q else ''}"
        if not cites:
            return head + "\n\nشاهدی برای پاسخ بازیابی نشد."
        body = "\n".join(f"• {c[1].strip()[:160]} [{c[0]}]" for c in cites[:6])
        return f"{head}\n\n{body}\n\nبرای تحلیل حقوقی واقعی، یک مدل واقعی (Claude Haiku) را در .env تنظیم کنید."

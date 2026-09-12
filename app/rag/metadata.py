"""
Rules-based metadata extraction — no LLM.

Iranian legal documents carry their key facts in a predictable header
("شماره پرونده:", "تاریخ دادنامه:", "مرجع صدور:", ...) or in a recognisable
first paragraph ("پرونده کلاسه ...", "جلسه مورخ ...", "دادگاه عمومی حقوقی X –
شعبه Y"). Pulling those with regex gives every document a set of filterable
fields cheaply, so retrieval can be scoped to a case number / court / year
without waiting on the extractor and without sending anything to a model.

Stored on `Document.doc_metadata`; used by the retriever's `filters` argument.
"""

import re

from app.rag.textnorm import normalize_fa

# case / کلاسه number: 4+ digits, optionally with / or -
_CASE = re.compile(
    r"(?:شماره\s+پرونده|پرونده\s+کلاسه|کلاسه|شماره\s+بایگانی)\s*[:：]?\s*([0-9][0-9/\-]{3,})"
)
_DATE = re.compile(
    r"(?:تاریخ\s+دادنامه|جلسه\s+مورخ|مورخ|تاریخ\s+رأی|تاریخ)\s*[:：]?\s*"
    r"(1[34][0-9]{2}/[0-9]{1,2}/[0-9]{1,2})"
)
_COURT = re.compile(
    r"(?:مرجع\s+صدور|دادگاه|شعبه\s+صادرکننده)\s*[:：]?\s*"
    r"([^\n]{3,80}?)(?:\n|$|،)"
)
_BRANCH = re.compile(r"شعبه\s+([0-9]{1,4}|اول|دوم|سوم|چهارم|پنجم|ششم|هفتم|هشتم|نهم|دهم)")
_GROUP = re.compile(r"گروه\s*[:：]?\s*(کیفری|حقوقی|خانواده|اطفال|تجدیدنظر|دیوان)")
_DOCKIND = re.compile(r"(دادنامه|صورت\s?جلسه|کیفرخواست|قرار|رأی|لایحه|دادخواست)")


def _first(rx, text):
    m = rx.search(text)
    return m.group(1).strip() if m else None


def extract_metadata(text: str) -> dict:
    t = normalize_fa(text)[:2000]  # the header/opening is all that matters
    out: dict = {}

    case = _first(_CASE, t)
    if case:
        out["case_number"] = case

    date = _first(_DATE, t)
    if date:
        out["date"] = date
        year = date.split("/")[0]
        if year.isdigit():
            out["year"] = year

    court = _first(_COURT, t)
    if court:
        court = re.sub(r"\s+", " ", court).strip(" -–،:")
        out["court"] = court[:80]
    branch = _first(_BRANCH, t)
    if branch:
        out["branch"] = f"شعبه {branch}"

    group = _first(_GROUP, t)
    if group:
        out["group"] = group

    kind = _first(_DOCKIND, t)
    if kind:
        out["doc_kind"] = kind.replace("  ", " ")

    return out

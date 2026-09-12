"""
Cases — the view of the archive lawyers actually think in.

A `Entry` is one extracted session/document. A *case* is every entry sharing a
case number (`entities.case_number`), folded together: its parties, its
representation, its events on one timeline, its topics and tags.

This is a port of `deriveCases()` from the old `app/static/app.html`, moved into
the domain layer so the UI only renders it. An entry with no case number becomes
a case of its own and is flagged `incomplete`, which is what feeds the
human-review queue.
"""

from typing import Any


def _text(value: Any) -> str:
    return str(value or "").strip()


def _as_strings(value: Any) -> list[str]:
    """Extraction is model output, so a field declared as a string sometimes
    comes back as a list (or a number). Normalise to a flat list of non-empty
    strings — without this, `topic` arriving as a list makes it into a set and
    raises `unhashable type: 'list'` several screens later."""
    if value is None or value == "":
        return []
    if isinstance(value, (list, tuple, set)):
        out = []
        for item in value:
            out.extend(_as_strings(item))
        return out
    return [str(value).strip()] if str(value).strip() else []


def derive_cases(entries: list[dict]) -> list[dict]:
    """Group entries into cases, newest/most-documented first."""
    groups: dict[str, dict] = {}
    for entry in entries:
        number = _text((entry.get("entities") or {}).get("case_number"))
        key = number or f"__u__{entry.get('id')}"
        groups.setdefault(key, {"number": number, "entries": []})["entries"].append(entry)

    cases = []
    for group in groups.values():
        rows = group["entries"]
        first = rows[0]
        parties: dict[str, str] = {}
        events: list[dict] = []
        representation: list[dict] = []
        topics: list[str] = []
        courts: list[str] = []
        related: list[str] = []
        related_links: list[dict] = []   # [{title, score, outcome, ...}] from the pipeline
        tags: list[str] = []

        for entry in rows:
            for party in entry.get("parties") or []:
                if isinstance(party, dict) and party.get("name"):
                    parties[_text(party["name"])] = _text(party.get("role")) or "other"
            for event in entry.get("events") or []:
                events.append({**event, "entry_id": entry.get("id")})
            for rep in entry.get("representation") or []:
                if rep and rep.get("lawyer"):
                    representation.append(rep)
            for tag in _as_strings(entry.get("tags")):
                if tag not in tags:
                    tags.append(tag)
            entities = entry.get("entities") or {}
            for topic in _as_strings(entities.get("topic")):
                if topic not in topics:
                    topics.append(topic)
            for court in _as_strings(entities.get("court")):
                if court not in courts:
                    courts.append(court)
            for rid in _as_strings(entry.get("related_ids")):
                if rid not in related:
                    related.append(rid)
            for link in entry.get("related") or []:
                if isinstance(link, dict) and link.get("title"):
                    key = link.get("entry_id") or link.get("document_id") or link["title"]
                    if key not in {l.get("entry_id") or l.get("document_id") or l["title"] for l in related_links}:
                        related_links.append(link)

        events.sort(key=lambda e: _text(e.get("date")))
        reasons = []
        if not group["number"]:
            reasons.append("شماره پرونده استخراج نشده")
        if not parties:
            reasons.append("طرفین استخراج نشده")

        cases.append({
            "id": group["number"] or first.get("id"),
            "number": group["number"],
            "title": first.get("title") or _text(first.get("summary"))[:60] or "پرونده بدون عنوان",
            "subject": topics[0] if topics else "—",
            "court": courts[0] if courts else "—",
            "entries": rows,
            "parties": [{"name": n, "role": r} for n, r in parties.items()],
            "representation": representation,
            "events": events,
            "topics": topics,
            "tags": tags,
            "related_ids": related,
            "related_links": related_links,
            "doc_ids": [e.get("document_id") for e in rows if e.get("document_id")],
            "incomplete": bool(reasons),
            "incomplete_reasons": reasons,
            "last_event_date": events[-1].get("date") if events else None,
            "text": "\n".join(_text(e.get("summary")) or _text(e.get("title")) for e in rows),
        })

    cases.sort(key=lambda c: (len(c["entries"]), _text(c["last_event_date"])), reverse=True)
    return cases


def all_events(cases: list[dict]) -> list[dict]:
    """Every event across every case, newest first — the رویدادها view."""
    events = []
    for case in cases:
        for event in case["events"]:
            events.append({
                **event,
                "case_id": case["id"],
                "case_title": case["title"],
                "case_number": case["number"],
            })
    events.sort(key=lambda e: _text(e.get("date")), reverse=True)
    return events


def tag_counts(cases: list[dict]) -> list[dict]:
    """Tag → number of cases carrying it, for the طبقه‌بندی view."""
    counts: dict[str, int] = {}
    for case in cases:
        for tag in case["tags"]:
            counts[tag] = counts.get(tag, 0) + 1
    return [
        {"tag": tag, "cases": n}
        for tag, n in sorted(counts.items(), key=lambda kv: -kv[1])
    ]

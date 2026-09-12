"""Convert the Iranian Courts Ruling JSON corpus into RAG-ready text files.

The source dataset is downloaded separately and is intentionally not committed:

    .venv/bin/hf download Moryjj/Iranian-Courts-Ruling --repo-type dataset \
        --local-dir data/external/iranian-courts-ruling-raw

Usage:
    python -m scripts.prepare_iranian_courts_rulings

The output can then be indexed with:
    python -m scripts.ingest data/farsi-courts
"""

import argparse
import json
from pathlib import Path


DEFAULT_SOURCE = Path("data/external/iranian-courts-ruling-raw/Dataset_BA.json")
DEFAULT_OUTPUT = Path("data/farsi-courts")


def _clean(value: object) -> str:
    return " ".join(str(value or "").split())


def _render(case_id: str, record: dict) -> str:
    """Preserve provenance and useful metadata alongside the ruling itself."""
    fields = (
        ("شناسه سند", case_id),
        ("شماره پرونده", record.get("شماره پرونده")),
        ("تاریخ دادنامه", record.get("تاریخ دادنامه")),
        ("گروه", record.get("گروه")),
        ("مرجع صدور", record.get("مرجع صدور")),
        ("عنوان", record.get("عنوان")),
        ("منبع", record.get("link")),
    )
    metadata = "\n".join(f"{label}: {_clean(value)}" for label, value in fields if _clean(value))
    message = _clean(record.get("پیام"))
    judgment = _clean(record.get("متن رای"))

    sections = [metadata]
    if message:
        sections.append(f"پیام رای:\n{message}")
    if judgment:
        sections.append(f"متن رای:\n{judgment}")
    return "\n\n".join(sections).strip() + "\n"


def prepare(source: Path, output: Path) -> tuple[int, int]:
    with source.open(encoding="utf-8") as handle:
        rows = json.load(handle)
    if not isinstance(rows, list):
        raise ValueError("Expected the dataset root to be a JSON list.")

    output.mkdir(parents=True, exist_ok=True)
    written = skipped = 0
    for position, wrapped in enumerate(rows, start=1):
        if not isinstance(wrapped, dict) or len(wrapped) != 1:
            skipped += 1
            continue
        case_id, record = next(iter(wrapped.items()))
        if not isinstance(record, dict):
            skipped += 1
            continue
        text = _render(str(case_id), record)
        if "متن رای:" not in text:
            skipped += 1
            continue
        # Case numbers can repeat across records, so the source row number is
        # included to make every RAG document identifier unique and stable.
        row_number = _clean(record.get("number")) or str(position)
        (output / f"court-ruling-{row_number.zfill(6)}-{case_id}.txt").write_text(
            text, encoding="utf-8"
        )
        written += 1
    return written, skipped


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if not args.source.is_file():
        parser.error(f"Dataset JSON was not found: {args.source}")
    written, skipped = prepare(args.source, args.output)
    print(f"Prepared {written:,} text files in {args.output} ({skipped:,} skipped).")

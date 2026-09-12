"""
Persian/Farsi text normalization for retrieval.

Legal documents here come from mixed sources (typed on Arabic keyboards, OCR,
copy-paste) so the same word appears written several ways. Normalizing both the
stored chunk text and the query to one form makes the lexical (full-text) half
of retrieval actually match. The changes are near-invisible to a Persian reader
— they do not touch spacing style (ZWNJ is left alone) or meaning.

  ي ك  (Arabic yeh/kaf)      -> ی ک  (Persian)
  ة ﺓ                        -> ه
  ئ ؤ                        -> ی و     (only the standalone forms)
  ٠-٩ ۰-۹  (Indic/Persian)   -> 0-9     (so case numbers like ۱۴۰۲۹۹ match 140299)
  ـ  (tatweel / kashida)     -> removed
  runs of spaces/tabs        -> one space
"""

import re

_TABLE = str.maketrans({
    "ي": "ی", "ك": "ک", "ﮐ": "ک", "ﮏ": "ک",
    "ة": "ه", "ۀ": "ه", "ﺓ": "ه",
    "ئ": "ی", "ؤ": "و",
    "ـ": "",
    "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4",
    "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
    "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4",
    "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
})

_SPACES = re.compile(r"[ \t ]+")


def normalize_fa(text: str) -> str:
    return _SPACES.sub(" ", (text or "").translate(_TABLE))


def sql_translate_args() -> tuple[str, str]:
    """`_TABLE` as arguments for Postgres `translate(text, from, to)`.

    The lexical index has to be built from text folded exactly the way
    `normalize_fa` folds a query, or an Arabic yeh in a stored entry will never
    match a Persian yeh typed in the search box. Deriving the pair from the same
    table is what keeps the two from drifting apart: characters that map to ""
    are placed last, where `translate` deletes anything past the end of `to`.
    """
    mapped = [(chr(src), dst) for src, dst in _TABLE.items() if dst]
    dropped = [chr(src) for src, dst in _TABLE.items() if not dst]
    return (
        "".join(src for src, _ in mapped) + "".join(dropped),
        "".join(dst for _, dst in mapped),
    )

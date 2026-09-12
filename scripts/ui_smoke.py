"""
Render every section of the Streamlit UI headlessly and fail on any error.

    python -m scripts.ui_smoke

Uses Streamlit's AppTest, so it needs the database (DATABASE_URL or the
embedded one) and a model the registry marks available — the offline mock
(`LLM_PROVIDER=mock`) is enough. CI runs this against pgvector; locally it is
the quickest answer to "did my change break a screen".
"""

import pathlib
import sys

from streamlit.testing.v1 import AppTest

from app.ui.nav import SECTIONS

APP = pathlib.Path(__file__).resolve().parent.parent / "streamlit_app.py"


def main() -> int:
    failed = 0
    for section_id, _number, label in SECTIONS:
        test = AppTest.from_file(str(APP), default_timeout=240)
        test.session_state["view"] = section_id
        try:
            test.run()
        except Exception as error:  # noqa: BLE001 — report and keep going
            print(f"FAIL  {section_id:10} {label}  run: {type(error).__name__}: {error}")
            failed += 1
            continue
        problems = [e.value for e in test.exception] + [e.value for e in test.error]
        if problems:
            print(f"FAIL  {section_id:10} {label}")
            for p in problems:
                print(f"      {str(p)[:300]}")
            failed += 1
        else:
            print(f"PASS  {section_id:10} {label}")
    print(f"-- {len(SECTIONS) - failed} passed, {failed} failed --")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

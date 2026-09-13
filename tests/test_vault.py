"""The Obsidian export and the graph read back from it.

No database and no vault on disk: `build_notes` is pure and the reader is
pointed at a temporary folder. That matters because CI has no vault at all —
`graphify-out/` is gitignored — so these tests have to prove the round trip
without one, and prove that a missing vault is an empty graph rather than a
crash.
"""

import types

import pytest

from app.rag import vaultmap, vaultsync


def _record(**fields):
    """A stand-in for a SQLAlchemy row: `build_notes` only reads attributes."""
    return types.SimpleNamespace(**fields)


def _state():
    case = _record(
        id="c1", case_number="۱۴۰۰۱۱۱", title="مطالبهٔ خسارت", case_type="بازیافت",
        insurance_line="شخص ثالث", court="دادگاه حقوقی کرج", branch="3", group="حقوقی",
        status="closed", stage="قطعی", filed_date="1400/05/21", decided_date="1400/11/21",
        outcome="رد دعوا",
    )
    law = _record(
        id="l1", law_title="قانون بیمه", article_no="30", law_year="۱۳۱۶",
        title="جانشینی بیمه‌گر", text="متن ماده", ref_key="قانون بیمه|30",
    )
    person = _record(id="p1", name="زهرا نظری", roles=["vakil_khande"])
    org = _record(id="o1", name="شرکت سهامی بیمه ایران", kind="insurer", roles=[])
    return {
        "cases": [case], "laws": [law], "persons": [person], "orgs": [org],
        "parties": [_record(case_id="c1", person_id="p1", org_id=None, role="vakil_khande"),
                    _record(case_id="c1", person_id=None, org_id="o1", role="khande")],
        "citations": [_record(case_id="c1", ref_id="l1", context="مبنای رد دفاع")],
        "entries": [_record(case_id="c1", tags=["بازیافت", "شخص ثالث"], summary="خلاصه")],
    }


def _export_into(tmp_path, state=None):
    vaultsync.VAULT_DIR = str(tmp_path)
    for note in vaultsync.build_notes(state or _state()):
        path = tmp_path / note["relpath"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(note["text"], encoding="utf-8")


@pytest.fixture(autouse=True)
def _restore_vault_dir():
    original = vaultsync.VAULT_DIR
    yield
    vaultsync.VAULT_DIR = original


def test_one_note_per_record():
    notes = vaultsync.build_notes(_state())
    assert {n["kind"] for n in notes} == {"case", "law", "person", "org"}
    assert len(notes) == 4


def test_case_note_links_to_its_parties_and_laws():
    case = next(n for n in vaultsync.build_notes(_state()) if n["kind"] == "case")
    assert "[[زهرا نظری]] — وکیل خوانده" in case["text"]
    assert "[[شرکت سهامی بیمه ایران]] — خوانده" in case["text"]
    assert "[[قانون بیمه — ماده 30]] — استناد به — مبنای رد دفاع" in case["text"]


def test_tags_carry_nothing_obsidian_rejects():
    """A tag is truncated at the first illegal character, which would split one
    cluster in two — «رجوع (م. ۶۶)» is a real case type in this archive."""
    state = _state()
    state["cases"][0].case_type = "رجوع تأمین اجتماعی (م. ۶۶)"
    case = next(n for n in vaultsync.build_notes(state) if n["kind"] == "case")
    tags = [line for line in case["text"].splitlines() if line.startswith("#آرشیو")]
    assert tags, "the note should carry a tag footer"
    for tag in tags[0].split():
        assert not set(tag) & set("()[]{}.،,:"), tag


def test_duplicate_display_names_stay_distinct():
    """Obsidian resolves a wikilink by basename, so two notes cannot share one."""
    state = _state()
    state["persons"].append(_record(id="p2", name="زهرا نظری", roles=[]))
    names = [n["name"] for n in vaultsync.build_notes(state) if n["kind"] == "person"]
    assert len(set(names)) == 2


def test_round_trip_through_the_vault(tmp_path):
    _export_into(tmp_path)
    graph = vaultmap.load()

    assert len(graph["nodes"]) == 4
    assert {n["kind"] for n in graph["nodes"]} == {"case", "law", "person", "org"}
    # Three links leave the case note: two parties and one citation.
    assert len(graph["edges"]) == 3
    case = next(n for n in graph["nodes"] if n["kind"] == "case")
    assert case["degree"] == 3
    assert case["case_number"] == "۱۴۰۰۱۱۱"
    assert case["uri"].startswith("obsidian://open?vault=")


def test_a_law_inherits_the_tag_of_the_case_citing_it(tmp_path):
    """Laws and people carry no tag of their own; without inheritance every
    node that is not a case would be grey and the clusters half empty."""
    _export_into(tmp_path)
    graph = vaultmap.load()
    law = next(n for n in graph["nodes"] if n["kind"] == "law")
    case = next(n for n in graph["nodes"] if n["kind"] == "case")
    assert case["tag"] and law["tag"] == case["tag"]
    assert law.get("inherited") is True


def test_code_notes_in_the_same_vault_are_not_in_the_graph(tmp_path):
    """The vault also holds a thousand notes graphify wrote about the source
    code. A link into one of them is not an edge, and the note is not a node."""
    _export_into(tmp_path)
    (tmp_path / "agent.py.md").write_text("# agent.py\n- [[۱۴۰۰۱۱۱ مطالبهٔ خسارت]]\n", encoding="utf-8")
    (tmp_path / vaultsync.ARCHIVE_DIR / "پرونده‌ها").glob("*.md")
    graph = vaultmap.load()
    assert all(n["name"] != "agent.py" for n in graph["nodes"])
    assert len(graph["nodes"]) == 4


def test_no_vault_is_an_empty_graph_not_an_error(tmp_path):
    """CI, the Docker image and a fresh clone have no vault, and section ۲۰ has
    to render there — `scripts/ui_smoke.py` renders every section."""
    vaultsync.VAULT_DIR = str(tmp_path / "nothing-here")
    assert vaultsync.vault_exists() is False
    graph = vaultmap.load()
    assert graph == {"nodes": [], "edges": [], "tags": [], "vault": None}

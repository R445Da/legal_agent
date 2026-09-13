"""«پرسش از آرشیو» — the counting tool, and the four faults its eval found.

Each test here is one of the mistakes the first run made against the real
archive. They are kept as tests because every one of them produced a confident
wrong number rather than an error, which is the failure mode that does not
announce itself.
"""

import pytest

from app.rag import archive_query as aq

pytestmark = pytest.mark.db


VOCAB = {
    "tags": {"تصادف": 9, "فقدان گواهینامه": 4, "رانندگی در حالت مستی": 1, "مستمری": 9},
    "insurance_lines": {"شخص ثالث": 34, "آتش‌سوزی": 11},
    "case_types": {"تقلب / جعل / کلاهبرداری بیمه‌ای": 8},
}


# --------------------------------------------------------------------------- #
# What the model returns is never trusted as-is
# --------------------------------------------------------------------------- #
def test_a_name_carrying_its_own_count_is_still_accepted():
    """The vocabulary is shown as «شخص ثالث (34)» and the model copies the line
    whole. The first eval rejected every label of one question for this."""
    keep, unknown = aq._kept(["شخص ثالث (34)", "آتش‌سوزی (۱۱)"], VOCAB["insurance_lines"])
    assert keep == ["شخص ثالث", "آتش‌سوزی"]
    assert unknown == []


def test_an_invented_label_never_reaches_the_arithmetic():
    keep, unknown = aq._kept(["تصادف", "تخلفات رانندگی"], VOCAB["tags"])
    assert keep == ["تصادف"]
    assert unknown == ["تخلفات رانندگی"]


def test_a_repeated_label_is_counted_once():
    keep, _ = aq._kept(["تصادف", "تصادف", "فقدان گواهینامه"], VOCAB["tags"])
    assert keep == ["تصادف", "فقدان گواهینامه"]


# --------------------------------------------------------------------------- #
# Which questions refine rather than search
# --------------------------------------------------------------------------- #
def test_status_questions_are_refinements():
    assert aq.is_refinement("از همان‌ها چند تا مختومه شده و چند تا هنوز جاری است؟")
    assert aq.is_refinement("از این‌ها چند تا در تجدیدنظر است؟")


def test_a_real_question_is_not_a_refinement():
    assert not aq.is_refinement("چند نوع پرونده در مورد تخلفات رانندگی داریم؟")
    assert not aq.is_refinement("پرونده‌های تقلب بیمه‌ای چند تاست؟")


# --------------------------------------------------------------------------- #
# The arithmetic, against the seeded archive
# --------------------------------------------------------------------------- #
async def test_vocabulary_is_the_archive_not_a_guess(db_session):
    vocab = await aq.vocabulary(db_session)
    assert vocab["tags"], "no tags in the seeded archive"
    assert all(isinstance(n, int) and n > 0 for n in vocab["tags"].values())
    # Counts are cases, not rows: a tag cannot cover more cases than exist.
    from sqlalchemy import func, select

    from app.db.models import LegalCase
    total = await db_session.scalar(select(func.count()).select_from(LegalCase))
    assert max(vocab["tags"].values()) <= total


async def test_vocabularies_intersect_and_labels_unite(db_session):
    """The fault that turned two cases into twenty-five.

    Two tags in one question are alternatives; a tag *and* a line are
    conditions. Unioning across vocabularies answered «تقلب در رشتهٔ آتش‌سوزی»
    with every fraud case plus every fire case.
    """
    vocab = await aq.vocabulary(db_session)
    line = next(iter(vocab["insurance_lines"]))
    tag = next(iter(vocab["tags"]))

    only_line = await aq.resolve(db_session, {"tags": [], "insurance_lines": [line],
                                              "case_types": []})
    only_tag = await aq.resolve(db_session, {"tags": [tag], "insurance_lines": [],
                                             "case_types": []})
    both = await aq.resolve(db_session, {"tags": [tag], "insurance_lines": [line],
                                         "case_types": []})
    assert both["count"] <= min(only_line["count"], only_tag["count"]), (
        "combining a tag with a line widened the result instead of narrowing it")
    assert set(both["case_ids"]) <= set(only_line["case_ids"])


async def test_within_narrows_to_the_previous_answer(db_session):
    vocab = await aq.vocabulary(db_session)
    line = next(iter(vocab["insurance_lines"]))
    full = await aq.resolve(db_session, {"tags": [], "insurance_lines": [line],
                                         "case_types": []})
    assert full["count"] > 1

    half = full["case_ids"][: full["count"] // 2]
    narrowed = await aq.resolve(db_session, {"tags": [], "insurance_lines": [line],
                                             "case_types": []}, within=half)
    assert narrowed["count"] == len(half)
    assert set(narrowed["case_ids"]) == set(half)


async def test_a_refinement_regroups_without_a_model(db_session):
    """«از همان‌ها چند تا مختومه شده؟» named no label, so label selection
    returned nothing and the tool reported zero — about a set it was holding."""
    from app.llm.mock_provider import MockProvider

    class Counting(MockProvider):
        calls = 0

        async def generate(self, *a, **k):
            type(self).calls += 1
            return await super().generate(*a, **k)

    vocab = await aq.vocabulary(db_session)
    line = next(iter(vocab["insurance_lines"]))
    seed = await aq.resolve(db_session, {"tags": [], "insurance_lines": [line],
                                         "case_types": []})

    llm = Counting()
    before = Counting.calls
    result = await aq.run(db_session, llm, "از همان‌ها چند تا مختومه شده است؟",
                          within=seed["case_ids"])

    assert result["count"] == seed["count"], "the refinement lost the set"
    assert result.get("refinement") is True
    assert Counting.calls == before, "a refinement should not call the model"
    assert sum(n for _, n in result["by_status"]) == seed["count"]
    # and it must not claim zero labels matched
    assert "۰ برچسب" not in aq.summarise(result)


async def test_counts_are_consistent_with_the_cases_returned(db_session):
    vocab = await aq.vocabulary(db_session)
    tag = max(vocab["tags"], key=lambda k: vocab["tags"][k])
    result = await aq.resolve(db_session, {"tags": [tag], "insurance_lines": [],
                                           "case_types": []})
    assert result["count"] == len(result["cases"]) == len(result["case_ids"])
    assert sum(n for _, n in result["by_status"]) == result["count"]
    assert result["count"] == vocab["tags"][tag]


async def test_nothing_matched_says_so_rather_than_zeroing_quietly(db_session):
    result = await aq.resolve(db_session, {"tags": ["برچسبی که وجود ندارد"],
                                           "insurance_lines": [], "case_types": []})
    assert result["count"] == 0
    text = aq.summarise({**result, "facets": {"tags": [], "insurance_lines": [],
                                              "case_types": [], "rejected": []},
                         "within": False})
    assert "هیچ پرونده‌ای" in text

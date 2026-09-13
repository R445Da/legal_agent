"""The sample prompts on the assistant's home screen.

They are shown to whoever opens the app, so they are checked here: a prompt
that is advertised and does not work is worse than no prompt at all. These
tests keep the list well-formed and run the archive group end to end, because
that group's prompts are the ones the counting tool is evaluated on.
"""

import pytest

from app.ui import prompts as lib


def test_every_group_says_what_it_is_for():
    assert lib.GROUPS
    ids = [g.id for g in lib.GROUPS]
    assert len(ids) == len(set(ids)), "two groups share an id"
    for group in lib.GROUPS:
        assert group.title.strip() and group.blurb.strip()
        assert group.prompts, f"group {group.id} advertises nothing"


def test_every_prompt_says_what_a_right_answer_looks_like():
    for prompt in lib.all_prompts():
        assert prompt.text.strip()
        assert prompt.note.strip(), f"no note on {prompt.text[:40]!r}"


def test_a_follow_up_never_comes_first():
    """«از همان‌ها…» refines the set on screen; offered cold it refines nothing."""
    for group in lib.GROUPS:
        if group.prompts:
            assert not group.prompts[0].follows, f"{group.id} opens with a follow-up"


def test_pinned_intents_are_real_routes():
    from app.rag.orchestrator import _INTENT_FA

    for prompt in lib.all_prompts():
        if prompt.intent:
            assert prompt.intent in _INTENT_FA, f"unknown intent {prompt.intent!r}"


# --------------------------------------------------------------------------- #
@pytest.mark.db
async def test_the_archive_prompts_all_run(db_session):
    """Every advertised counting prompt reaches an answer with a real count.

    The offline model does not pick labels as well as a hosted one, so this
    asserts the shape and the arithmetic — that the tool runs, that counts agree
    with the cases returned, and that a follow-up keeps the set — rather than a
    particular number.
    """
    from app.llm.mock_provider import MockProvider
    from app.rag import archive_query as aq

    llm = MockProvider()
    previous: list[str] | None = None

    for prompt in lib.eval_prompts("archive"):
        result = await aq.run(db_session, llm, prompt.text,
                              within=previous if prompt.follows else None)

        assert result["count"] == len(result["case_ids"]) == len(result["cases"])
        assert sum(n for _, n in result["by_status"]) == result["count"]
        assert aq.summarise(result).strip()
        # nothing invented reaches the arithmetic
        assert not (set(result["facets"]["tags"]) & set(result["facets"]["rejected"]))

        if prompt.follows:
            assert result["within"] is True
            assert set(result["case_ids"]) <= set(previous or []), (
                "a follow-up widened the set instead of refining it")
        else:
            previous = result["case_ids"]

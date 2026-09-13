"""Conversation-mode filing: the reply parser, the question, and the whole
dialogue on the seeded archive with the offline model."""

import pytest

from app.rag import conversation
from app.rag.workflow import WorkflowState

PENDING = ["entities.case_number"]


def test_labelled_line_and_persian_digits():
    out = conversation.regex_merge("شماره پرونده: ۱۴۰۲۱۱۲۲۳۳", PENDING)
    assert out["patch"] == {"entities.case_number": "1402112233"}
    assert not out["confirm"] and not out["cancel"]


def test_case_number_inside_prose_and_bare_number():
    out = conversation.regex_merge("کلاسهٔ پرونده ۱۴۰۲/۱۲۳۴۵ است و بس", PENDING)
    assert out["patch"]["entities.case_number"] == "1402/12345"
    assert conversation.regex_merge("۱۴۰۲۰۰۱۲۳۴", PENDING)["patch"] == {"entities.case_number": "1402001234"}


def test_multi_field_reply():
    out = conversation.regex_merge("عنوان: دعوای بازیافت\nخلاصه: بیمه‌گر پس از پرداخت خسارت رجوع کرد\nمرجع: شعبهٔ ۳", [])
    assert out["patch"] == {"title": "دعوای بازیافت", "summary": "بیمه‌گر پس از پرداخت خسارت رجوع کرد",
                            "entities.court": "شعبهٔ ۳"}


def test_confirm_cancel_skip_words():
    assert conversation.regex_merge("تأیید", [])["confirm"] is True
    assert conversation.regex_merge("همین درست است، ثبت کن", [])["confirm"] is True
    assert conversation.regex_merge("انصراف", PENDING)["cancel"] is True
    assert conversation.regex_merge("رد شو", PENDING)["skip"] == PENDING
    # a long message that merely contains a confirm word is not a confirmation
    long = "بله، خوانده در جلسه حاضر شد و دادگاه پس از استماع اظهارات طرفین به کارشناسی ارجاع داد"
    assert conversation.regex_merge(long, [])["confirm"] is False


def test_single_pending_field_takes_the_whole_reply():
    out = conversation.regex_merge("دعوای بازیافت خسارت از رانندهٔ مقصر", ["title"])
    assert out["patch"] == {"title": "دعوای بازیافت خسارت از رانندهٔ مقصر"}


def test_propose_message_lists_found_and_missing():
    state = WorkflowState(draft={"title": "دعوای بازیافت", "summary": "", "entities": {"court": "شعبهٔ ۳"},
                                 "parties": [{"name": "بیمه ایران", "role": "khahan"}], "legal_refs": [{"law": "قانون بیمه"}]})
    message = conversation.propose_message(state)
    assert "عنوان: دعوای بازیافت" in message and "مرجع: شعبهٔ ۳" in message and "طرفین: بیمه ایران" in message
    assert "خلاصه" in message and "شمارهٔ پرونده" in message and "«رد شو»" in message
    full = WorkflowState(draft={"title": "t", "summary": "s", "entities": {"case_number": "1"}})
    assert "چیزی کم نیست" in conversation.propose_message(full)


def test_skipped_fields_are_not_asked_again():
    state = WorkflowState(draft={"title": "t", "summary": "s", "entities": {}},
                          conversation={"skipped": ["entities.case_number"], "turns": []})
    assert conversation.missing_paths(state) == []


# --------------------------------------------------------------------------- #
FILING = (
    "صورت‌جلسهٔ رسیدگی شعبهٔ ۳ دادگاه حقوقی تهران\n"
    "خواهان: شرکت سهامی بیمه ایران (با وکالت آقای رضا کریمی)\n"
    "خوانده: آقای علی مرادی\n"
    "موضوع: بازیافت خسارت پرداختی از رانندهٔ مقصر\n"
    "دادگاه با استناد به ماده ۳۰ قانون بیمه موضوع را به کارشناسی ارجاع داد."
)


@pytest.mark.db
async def test_dialogue_walks_its_queue_and_commits(db_session):
    """The gate is a queue of questions, one per turn, ending at the commit."""
    from sqlalchemy import select

    from app.db.models import LegalCase
    from app.llm.mock_provider import MockProvider
    from app.rag import workflow

    llm = MockProvider()
    view = await workflow.start(db_session, raw_text=FILING, source="test/conversation", llm=llm,
                                mode="conversation", forced_intent="archive")
    assert view["status"] == "awaiting_input" and conversation.is_waiting(view)

    # The opening turn still says what was extracted; the queue follows it.
    labels = next(s for s in view["steps"] if s["step_id"] == "labels")
    assert labels["payload"]["mode"] == "conversation"
    assert "از متن شما" in labels["payload"]["message"]
    queue = view["state"]["conversation"]["queue"]
    assert [q["id"] for q in queue][:2] == ["title", "entities.case_number"]
    assert queue[-1]["id"] == "commit"
    assert conversation.current_question(view["state"]["conversation"])["id"] == "title"

    # A labelled reply lands on the field it names, even though the question on
    # screen is about the title — and the unanswered question is asked again.
    view = await conversation.turn(db_session, view["id"], llm, "شماره پرونده: ۱۴۰۲۱۱۲۲۳۳")
    assert view["status"] == "awaiting_input"
    assert view["state"]["draft"]["entities"]["case_number"] == "1402112233"
    assert conversation.current_question(view["state"]["conversation"])["id"] == "title"

    # Now walk the rest of the queue: «تأیید» answers whatever is asked, and
    # the last question files the record.
    for _ in range(len(queue) + 4):
        if view["status"] != "awaiting_input":
            break
        view = await conversation.turn(db_session, view["id"], llm, "تأیید")

    assert view["status"] == "committed" and view["entry_id"]
    conv = view["state"]["conversation"]
    assert conv["confirmed"] is True
    assert conversation.current_question(conv) is None
    # Every question got its own pair of turns.
    assert [t["role"] for t in conv["turns"]][:3] == ["assistant", "user", "assistant"]

    row = await db_session.scalar(select(LegalCase).where(LegalCase.case_number == "1402112233"))
    assert row is not None

    with pytest.raises(ValueError):
        await conversation.turn(db_session, view["id"], llm, "دوباره")


@pytest.mark.db
async def test_a_chip_answer_costs_no_model_call(db_session):
    """Answering the question on screen is settled by `answer_question()`; the
    model is only asked when the reply cannot be read deterministically."""
    from app.llm.mock_provider import MockProvider
    from app.rag import workflow

    class Counting(MockProvider):
        calls = 0

        async def generate(self, *a, **k):
            type(self).calls += 1
            return await super().generate(*a, **k)

    llm = Counting()
    view = await workflow.start(db_session, raw_text=FILING, source="test/conversation-chip", llm=llm,
                                mode="conversation", forced_intent="archive")
    before = Counting.calls
    view = await conversation.turn(db_session, view["id"], llm, "تأیید")
    assert Counting.calls == before
    assert conversation.current_question(view["state"]["conversation"])["id"] != "title"


@pytest.mark.db
async def test_dialogue_cancel_abandons(db_session):
    from app.llm.mock_provider import MockProvider
    from app.rag import workflow

    llm = MockProvider()
    view = await workflow.start(db_session, raw_text=FILING, source="test/conversation-cancel", llm=llm,
                                mode="conversation", forced_intent="archive")
    view = await conversation.turn(db_session, view["id"], llm, "انصراف")
    assert view["status"] == "abandoned"

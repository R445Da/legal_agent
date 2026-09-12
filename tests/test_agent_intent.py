"""End to end on the seeded archive with the offline model (marked `db`)."""

import uuid

import pytest

from app.db.models import AssistantAnswer
from app.llm.mock_provider import MockProvider
from app.rag.orchestrator import run_assistant

pytestmark = pytest.mark.db

QUESTION = "پرونده‌های بازیافت از رانندهٔ مقصر طبق ماده ۱۶ قانون بیمه اجباری چطور تمام شده‌اند؟"


async def test_agent_intent_runs_tools_and_persists(db_session):
    res = await run_assistant(db_session, MockProvider(), QUESTION, force_intent="agent")

    assert res["intent"] == "agent"
    trail = res["provenance"]["tool_trail"]
    assert {row["tool"] for row in trail} >= {"search_cases", "search_law"}
    assert res["provenance"]["evidence"], "the ledger should have numbered the hits"
    assert res["provenance"]["grounding"]["status"] in ("ok", "partial")
    assert res["provenance"]["usage"]["calls"] == 2
    assert res["provenance"]["loop"] == "text"        # the mock has no native tool turns

    row = await db_session.get(AssistantAnswer, uuid.UUID(res["answer_id"]))
    assert row is not None and row.intent == "agent" and row.provenance["tool_trail"]


async def test_law_and_cases_routes_carry_provenance(db_session):
    law = await run_assistant(db_session, MockProvider(), "ماده ۳۰ قانون بیمه چه می‌گوید؟", force_intent="law")
    assert law["provenance"]["evidence"] and law["provenance"]["evidence"][0]["kind"] == "law"
    assert law["provenance"]["grounding"]["status"] in ("ok", "partial")
    assert law["answer_id"]

    cases = await run_assistant(db_session, MockProvider(), "پرونده‌های مشابه جانشینی", force_intent="cases")
    assert cases["provenance"]["evidence"] and cases["provenance"]["evidence"][0]["kind"] == "case"
    # one call for the answer, one for the comparative advice over similar cases
    assert cases["provenance"]["usage"]["calls"] == 2


async def test_workflow_step_payload_carries_usage(db_session):
    from app.rag import workflow

    text = ("صورت‌جلسهٔ پروندهٔ کلاسه ۱۴۰۲۱۱۲۲۳۳ شعبهٔ ۱ دادگاه حقوقی تهران. خواهان: شرکت سهامی بیمه ایران "
            "(با وکالت آقای رضا کریمی)، خوانده: آقای علی مرادی. موضوع: بازیافت خسارت پرداختی. "
            "دادگاه با استناد به ماده ۳۰ قانون بیمه به کارشناسی ارجاع داد.")
    view = await workflow.start(db_session, raw_text=text, source="test/usage", llm=MockProvider(),
                                mode="auto", forced_intent="archive")
    assert view["status"] == "committed"
    extract = next(s for s in view["steps"] if s["step_id"] == "extract")
    assert extract["payload"]["usage"]["calls"] == 1

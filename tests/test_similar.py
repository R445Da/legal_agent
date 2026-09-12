"""Graph-expanded similar cases on the seeded archive, and the outcome rules."""

import pytest

from app.rag import similar


def test_outcome_lessons_rules():
    cases = [
        {"case_number": "1", "title": "a", "outcome": "حکم به پرداخت خسارت به بیمه‌گر — مرور زمان رد شد", "status": "closed"},
        {"case_number": "2", "title": "b", "outcome": "قرار رد دعوا به سبب مرور زمان", "status": "closed"},
        {"case_number": "3", "title": "c", "outcome": "ارجاع به کارشناسی", "status": "open"},
        {"case_number": "4", "title": "d", "outcome": "", "status": "open"},
        {"case_number": "5", "title": "e", "outcome": "نتیجهٔ غیرمعمول", "status": "closed"},
    ]
    lessons = similar.outcome_lessons(cases)
    assert [c["case_number"] for c in lessons["worked"]] == ["1"]
    assert [c["case_number"] for c in lessons["failed"]] == ["2"]
    assert [c["case_number"] for c in lessons["pending"]] == ["3", "4"]
    assert [c["case_number"] for c in lessons["unknown"]] == ["5"]
    assert lessons["failed"][0]["point"] == "مرور زمان"
    assert lessons["summary"].startswith("1 پذیرفته‌شده · 1 ردشده · 2 در جریان")


def test_case_blocks_continue_numbering():
    cases = [{"id": "x", "case_number": "140201", "title": "t", "outcome": "رد دعوا", "why": ["استناد مشترک به مادهٔ ۳۰"]}]
    blocks, evidence = similar.case_blocks(cases, offset=3)
    assert blocks.startswith("[4] پروندهٔ 140201")
    assert "علت شباهت: استناد مشترک" in blocks
    assert evidence[0]["n"] == 4 and evidence[0]["kind"] == "case" and evidence[0]["why"]


@pytest.mark.db
async def test_expand_from_article_reaches_citing_cases(db_session):
    from sqlalchemy import select

    from app.db.models import LegalReference

    article = await db_session.scalar(
        select(LegalReference).where(LegalReference.law_title == "قانون بیمه", LegalReference.article_no == "30")
    )
    assert article is not None, "the seed should have article 30 of قانون بیمه"
    found = await similar.expand(db_session, nodes=[("law", str(article.id))])
    assert found, "the seeded subrogation cases cite article 30"
    best = max(found.values(), key=lambda v: v["score"])
    assert best["why"] and best["why"][0].startswith("استناد مشترک به")
    path = best["paths"][0]
    assert path[0]["type"] == "law" and path[-1]["type"] == "case"


@pytest.mark.db
async def test_expand_from_case_scores_shared_articles_over_shared_insurer(db_session):
    from sqlalchemy import select

    from app.db.models import LegalCase

    seed = await db_session.scalar(
        select(LegalCase).where(LegalCase.case_type == "جانشینی / بازیافت").limit(1)
    )
    assert seed is not None
    found = await similar.expand(db_session, case_ids=[str(seed.id)])
    assert found and str(seed.id) not in found
    ranked = sorted(found.values(), key=lambda v: -v["score"])
    top_reasons = " ".join(ranked[0]["why"])
    assert "استناد مشترک" in top_reasons or "قبلاً" in top_reasons
    # a hub node (the insurer) alone must not outrank a shared article
    assert all("degree" in link for link in ranked[0]["links"])


@pytest.mark.db
async def test_similar_cases_for_a_law_question(db_session):
    from app.rag.lawbase import search_laws

    refs = await search_laws(db_session, "ماده ۳۰ قانون بیمه جانشینی", limit=3)
    items = await similar.similar_cases(
        db_session, question="بیمه‌گر پس از پرداخت خسارت چگونه به مقصر رجوع می‌کند؟", refs=refs, top_k=5,
    )
    assert 1 <= len(items) <= 5
    for item in items:
        assert item["case_number"] and item["why"] and "score" in item
    assert any(any(w.startswith("استناد مشترک") for w in item["why"]) for item in items)


@pytest.mark.db
async def test_law_route_carries_similar_cases_and_advice(db_session):
    from app.llm.mock_provider import MockProvider
    from app.rag.orchestrator import run_assistant

    res = await run_assistant(db_session, MockProvider(), "ماده ۳۰ قانون بیمه دربارهٔ جانشینی چه می‌گوید؟", force_intent="law")
    assert res["similar_cases"] and res["lessons"]["summary"]
    assert res.get("advice")
    kinds = {e["kind"] for e in res["provenance"]["evidence"]}
    assert kinds == {"law", "case"}
    ns = [e["n"] for e in res["provenance"]["evidence"]]
    assert ns == list(range(1, len(ns) + 1))
    assert any(s["name"] == "پرونده‌های مشابه از گراف" for s in res["steps"])


@pytest.mark.db
async def test_expand_for_tool_on_a_case(db_session):
    from sqlalchemy import select

    from app.db.models import LegalCase

    seed = await db_session.scalar(select(LegalCase).limit(1))
    out = await similar.expand_for_tool(db_session, "case", seed.case_number)
    assert out["cases"] and out["candidates"] >= len(out["cases"])
    assert all(c["why"] for c in out["cases"])

"""A question that names someone the archive knows is answered from the party
table, not by searching case text.

This pins a bug that came back repeatedly: «وکیل رضا کریمی در چه پرونده‌هایی
بوده؟» reported that the lawyer appeared in no case at all, while the archive
held twenty-one party rows for them. The cause was that `search_cases()` runs
full-text search over the case table, whose searchable text is built from the
number, title, type, court, summary and outcome — the parties are not in it. So
the search returned unrelated cases and the model, reading them honestly, said
the person was not there.
"""

import pytest

from app.rag import casebase

pytestmark = pytest.mark.db


async def _a_lawyer(session):
    """Any person the seeded archive records as a lawyer on some case."""
    from sqlalchemy import func, select

    from app.db.models import CaseParty, Person

    row = (await session.execute(
        select(Person, func.count(CaseParty.id).label("n"))
        .join(CaseParty, CaseParty.person_id == Person.id)
        .where(CaseParty.role.like("vakil%"))
        .group_by(Person.id).order_by(func.count(CaseParty.id).desc()).limit(1)
    )).first()
    return row


async def test_a_name_in_the_question_is_found(db_session):
    row = await _a_lawyer(db_session)
    assert row, "the seeded archive has no lawyer to ask about"
    person, _ = row

    found = await casebase.named_entities(db_session, f"وکیل {person.name} در چه پرونده‌هایی بوده؟")
    assert [r.name for _, r in found] == [person.name]


async def test_a_question_with_no_known_name_finds_none(db_session):
    found = await casebase.named_entities(
        db_session, "پرونده‌های بازیافت خسارت از رانندهٔ فاقد گواهینامه چطور تمام شده‌اند؟")
    assert found == []


async def test_the_roster_is_answered_from_the_party_table(db_session):
    """The regression itself: the answer names their cases instead of denying
    they exist, and it costs no model call."""
    from app.llm.mock_provider import MockProvider

    row = await _a_lawyer(db_session)
    person, expected = row

    class Counting(MockProvider):
        calls = 0

        async def generate(self, *a, **k):
            type(self).calls += 1
            return await super().generate(*a, **k)

    llm = Counting()
    res = await casebase.answer_case_question(
        db_session, llm, f"وکیل {person.name} در چه پرونده‌هایی بوده؟")

    assert res.get("entity"), "the question was not recognised as being about a person"
    assert res["entity"]["name"] == person.name
    assert len(res["cases"]) == expected
    assert person.name in res["answer"]
    # The failure mode was a confident denial; make sure it cannot return.
    assert "یافت نشد" not in res["answer"]
    assert "ثبت نشده" not in res["answer"]
    # Every listed case carries the role that person held there.
    assert all(c.get("role_fa") for c in res["cases"])
    # A join needs no model, and the roster is not widened to other people's
    # cases — that is what buried it before.
    assert Counting.calls == 0
    assert res.get("skip_similar") is True


async def test_an_organisation_is_recognised_too(db_session):
    from sqlalchemy import func, select

    from app.db.models import CaseParty, Organization

    row = (await db_session.execute(
        select(Organization, func.count(CaseParty.id))
        .join(CaseParty, CaseParty.org_id == Organization.id)
        .group_by(Organization.id).order_by(func.count(CaseParty.id).desc()).limit(1)
    )).first()
    if not row:
        pytest.skip("the seeded archive has no organisation with cases")
    org, expected = row

    found = await casebase.named_entities(db_session, f"پرونده‌های {org.name} را نشان بده")
    assert org.name in [r.name for _, r in found]

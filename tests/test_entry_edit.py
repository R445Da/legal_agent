"""Proposing an edit, and the conversation that remembers what is being edited.

The invariant under test is that a chat message cannot change the archive on
its own. `propose_edit` and `propose_append` are the only tools that touch a
record, and neither writes — they return the current value beside the new one
for a human to confirm, and `entryedit.apply` is the single path to the
database.
"""

import pytest

from app.rag import catalog, conversations, entryedit

pytestmark = pytest.mark.db


async def _an_entry(db_session):
    rows = await catalog.list_entries(db_session)
    assert rows, "the seeded archive has no entries"
    return rows[0]


# --------------------------------------------------------------------------- #
# Proposals
# --------------------------------------------------------------------------- #
async def test_a_proposal_does_not_write(db_session):
    entry = await _an_entry(db_session)
    before = await catalog.get_entry(db_session, entry["id"])

    proposal = await entryedit.propose_edit(db_session, entry["id"], "عنوان", "عنوان تازه")

    assert proposal["new"] == "عنوان تازه"
    assert proposal["old"] == before["title"]
    after = await catalog.get_entry(db_session, entry["id"])
    assert after["title"] == before["title"], "proposing must not change the record"


async def test_confirming_applies_exactly_one_field(db_session):
    entry = await _an_entry(db_session)
    before = await catalog.get_entry(db_session, entry["id"])

    proposal = await entryedit.propose_edit(db_session, entry["id"], "عنوان", "عنوان تأییدشده")
    await entryedit.apply(db_session, proposal)

    after = await catalog.get_entry(db_session, entry["id"])
    assert after["title"] == "عنوان تأییدشده"
    assert after["summary"] == before["summary"], "no other field may move"


async def test_a_facet_edit_merges_rather_than_replacing_entities(db_session):
    """`entities` holds several facets at once; setting the docket number must
    not drop the court and the topic beside it."""
    entry = await _an_entry(db_session)
    before = (await catalog.get_entry(db_session, entry["id"]))["entities"] or {}

    proposal = await entryedit.propose_edit(db_session, entry["id"], "شمارهٔ پرونده", "۱۴۰۴۹۹۹۹۹۹")
    assert proposal["field"] == "entities" and proposal["facet"] == "case_number"
    await entryedit.apply(db_session, proposal)

    after = (await catalog.get_entry(db_session, entry["id"]))["entities"] or {}
    assert after["case_number"] == "۱۴۰۴۹۹۹۹۹۹"
    for key in ("court", "topic"):
        if before.get(key):
            assert after.get(key) == before[key], f"{key} was lost"


async def test_an_unknown_field_is_refused_with_the_allowed_ones(db_session):
    entry = await _an_entry(db_session)
    with pytest.raises(entryedit.EditError) as error:
        await entryedit.propose_edit(db_session, entry["id"], "قیمت", "۱۰۰")
    assert "عنوان" in str(error.value), "the refusal should name what is allowed"


async def test_raw_text_cannot_be_edited_from_the_chat(db_session):
    """Rewriting a filed record's source text from a chat line is a re-filing,
    not an edit, and must go through the pipeline."""
    entry = await _an_entry(db_session)
    with pytest.raises(entryedit.EditError):
        await entryedit.propose_edit(db_session, entry["id"], "raw_text", "متن تازه")


# --------------------------------------------------------------------------- #
# Appending to a list field
# --------------------------------------------------------------------------- #
async def test_appending_an_event_keeps_the_existing_timeline(db_session):
    """`update_entry` replaces a list field, so a proposal that carried only
    the new event would silently delete the rest of the timeline."""
    entry = await _an_entry(db_session)
    before = (await catalog.get_entry(db_session, entry["id"]))["events"] or []

    proposal = await entryedit.propose_append(
        db_session, entry["id"], "رویدادها", "۱۴۰۳/۰۵/۱۲ جلسهٔ کارشناسی")
    assert len(proposal["new"]) == len(before) + 1
    await entryedit.apply(db_session, proposal)

    after = (await catalog.get_entry(db_session, entry["id"]))["events"] or []
    assert len(after) == len(before) + 1
    assert after[-1]["date"] == "۱۴۰۳/۰۵/۱۲"
    assert after[-1]["description"] == "جلسهٔ کارشناسی"


async def test_appending_to_a_scalar_field_is_refused(db_session):
    entry = await _an_entry(db_session)
    with pytest.raises(entryedit.EditError):
        await entryedit.propose_append(db_session, entry["id"], "عنوان", "چیزی")


# --------------------------------------------------------------------------- #
# The conversation that remembers
# --------------------------------------------------------------------------- #
async def test_a_conversation_keeps_its_turns(db_session):
    convo = await conversations.start(db_session, source="test")
    await conversations.add_message(db_session, convo["id"], role="user", text="سلام")
    await conversations.add_message(db_session, convo["id"], role="assistant", text="درود", intent="chat")

    loaded = await conversations.get(db_session, convo["id"])
    assert [m["role"] for m in loaded["messages"]] == ["user", "assistant"]
    assert loaded["title"] == "سلام", "the first question names the thread"


async def test_the_focus_survives_and_is_what_a_follow_up_resolves_to(db_session):
    """«نشانش بده» after an edit has to reach the entry that was edited."""
    entry = await _an_entry(db_session)
    convo = await conversations.start(db_session, source="test")

    await conversations.set_focus(
        db_session, convo["id"], kind="entry", id=entry["id"], label=entry.get("title") or "")

    focus = await conversations.get_focus(db_session, convo["id"])
    assert focus["kind"] == "entry" and focus["id"] == str(entry["id"])
    # and it is still there when the thread is reopened
    assert (await conversations.get(db_session, convo["id"]))["focus"]["id"] == str(entry["id"])


async def test_deleting_a_conversation_removes_its_turns(db_session):
    convo = await conversations.start(db_session, source="test")
    await conversations.add_message(db_session, convo["id"], role="user", text="پاک شو")

    assert await conversations.remove(db_session, convo["id"]) is True
    assert await conversations.get(db_session, convo["id"]) is None


async def test_history_is_oldest_first_and_bounded(db_session):
    convo = await conversations.start(db_session, source="test")
    for i in range(6):
        await conversations.add_message(db_session, convo["id"], role="user", text=f"پیام {i}")

    turns = await conversations.history(db_session, convo["id"], limit=3)
    assert [t["text"] for t in turns] == ["پیام 3", "پیام 4", "پیام 5"]

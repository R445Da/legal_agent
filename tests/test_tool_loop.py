"""The tool loop: native transcript, evidence numbering, dedupe, fallbacks."""

from app.llm.base import flatten_transcript
from app.rag import tools
from app.rag.tools import EvidenceLedger, Tool, iter_with_tools, loop_mode, run_with_tools
from tests.conftest import FakeProvider, FakeTextProvider, resp

_ARTICLE = {"id": "law-1", "cite": "مادهٔ ۳۰ قانون بیمه", "title": "جانشینی بیمه‌گر",
            "text": "بیمه‌گر در حدود خسارتی که پرداخته قائم‌مقام بیمه‌گذار است."}
_CASE = {"id": "case-1", "case_number": "۱۴۰۲۰۰۱", "title": "بازیافت از رانندهٔ مقصر",
         "case_type": "جانشینی / بازیافت", "insurance_line": "بدنه خودرو", "court": "دادگاه حقوقی",
         "status": "مختومه", "outcome": "حکم به پرداخت خسارت به بیمه‌گر"}


def fake_tools() -> list[Tool]:
    async def law(session, llm, *, query="", limit=None, **_):
        return {"articles": [_ARTICLE]}

    async def cases(session, llm, *, query="", limit=None, **_):
        return {"cases": [_CASE]}

    async def boom(session, llm, **_):
        raise RuntimeError("db down")

    schema = {"type": "object", "properties": {"query": {"type": "string"},
                                               "limit": {"type": ["integer", "null"]}}, "required": ["query"]}
    return [
        Tool("search_law", "قوانین", schema, law, evidence=tools._ev_articles),
        Tool("search_cases", "پرونده‌ها", schema, cases, evidence=tools._ev_cases),
        Tool("boom", "خراب", {"type": "object", "properties": {}}, boom),
    ]


def _two_calls():
    return resp(tool_calls=[
        {"id": "c1", "name": "search_law", "arguments": {"query": "ماده ۳۰", "limit": None}},
        {"id": "c2", "name": "search_cases", "arguments": {"query": "بازیافت", "limit": None}},
    ], turn=[{"type": "tool_use", "id": "c1", "name": "search_law", "input": {"query": "ماده ۳۰"}},
             {"type": "tool_use", "id": "c2", "name": "search_cases", "input": {"query": "بازیافت"}}])


ANSWER = "بیمه‌گر پس از پرداخت خسارت قائم‌مقام بیمه‌گذار می‌شود [1]. پروندهٔ مشابه با حکم به پرداخت تمام شد [۲]."


async def test_native_loop_numbers_evidence_and_replays_turn():
    provider = FakeProvider([_two_calls(), resp(text=ANSWER)])
    result = await run_with_tools(provider, None, "Question: بازیافت", system="sys", tools=fake_tools())

    assert result.text == ANSWER
    assert result.mode == "native" and result.rounds == 2
    assert [e["n"] for e in result.evidence] == [1, 2]
    assert result.evidence[0]["kind"] == "law" and result.evidence[1]["case_number"] == "۱۴۰۲۰۰۱"
    assert [row["tool"] for row in result.tool_log] == ["search_law", "search_cases"]
    assert result.tool_log[0]["evidence_ns"] == [1] and result.tool_log[1]["evidence_ns"] == [2]
    assert result.usage["calls"] == 2 and result.usage["input_tokens"] == 200

    second = provider.calls[1]
    assert second["method"] == "chat" and second["cache"] is True and second["tool_choice"] == "auto"
    messages = second["messages"]
    assert messages[0] == {"role": "user", "content": "Question: بازیافت"}
    assert messages[1]["role"] == "assistant" and messages[1]["turn"][0]["id"] == "c1"
    tool_turns = [m for m in messages if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in tool_turns] == ["c1", "c2"]
    assert "[1] (ماده) مادهٔ ۳۰ قانون بیمه" in tool_turns[0]["content"]
    assert "[2] (پرونده) ۱۴۰۲۰۰۱" in tool_turns[1]["content"]
    assert not any(m["is_error"] for m in tool_turns)
    # strict-ready specs reach the provider
    assert all(spec["strict"] for spec in second["tools"])


async def test_repeat_call_is_not_rerun():
    twice = resp(tool_calls=[
        {"id": "c1", "name": "search_law", "arguments": {"query": "ماده ۳۰"}},
        {"id": "c2", "name": "search_law", "arguments": {"query": "ماده ۳۰"}},
    ])
    provider = FakeProvider([twice, resp(text="پاسخ کوتاه با استناد [1].")])
    result = await run_with_tools(provider, None, "Question: x", system="sys", tools=fake_tools())

    assert len(result.evidence) == 1
    assert result.tool_log[1].get("repeat") is True
    tool_turns = [m for m in provider.calls[1]["messages"] if m["role"] == "tool"]
    assert "قبلاً" in tool_turns[1]["content"]


async def test_max_rounds_then_forced_answer():
    provider = FakeProvider([_two_calls(), _two_calls(), resp(text="پاسخ نهایی [1]")])
    result = await run_with_tools(provider, None, "Question: x", system="sys", tools=fake_tools(), max_rounds=2)

    assert result.rounds == 2 and result.text == "پاسخ نهایی [1]"
    final = provider.calls[2]
    assert final["tool_choice"] == "none" and final["tools"]  # same tool list keeps the cache prefix
    assert final["messages"][-1] == {"role": "user", "content": "Now answer directly, without calling any more tools."}


async def test_unknown_tool_and_handler_error_are_flagged():
    calls = resp(tool_calls=[
        {"id": "c1", "name": "nope", "arguments": {}},
        {"id": "c2", "name": "boom", "arguments": {}},
    ])
    provider = FakeProvider([calls, resp(text="نتیجه‌ای نبود.")])
    result = await run_with_tools(provider, None, "Question: x", system="sys", tools=fake_tools())

    assert result.tool_log[0]["error"] == "unknown tool"
    assert "RuntimeError" in result.tool_log[1]["error"]
    tool_turns = [m for m in provider.calls[1]["messages"] if m["role"] == "tool"]
    assert all(m["is_error"] for m in tool_turns)
    assert result.evidence == []


async def test_text_mode_flattens_for_providers_without_native_turns():
    provider = FakeTextProvider([_two_calls(), resp(text="پاسخ متنی [1] و [2].")])
    result = await run_with_tools(provider, None, "Question: x", system="sys", tools=fake_tools())

    assert result.mode == "text"
    assert provider.calls[0]["method"] == "generate" and provider.calls[0]["tools"]
    prompt = provider.calls[1]["prompt"]
    assert prompt.startswith("Question: x")
    assert "You called tools and received:" in prompt
    assert "[1] (ماده) مادهٔ ۳۰ قانون بیمه" in prompt and "search_law(query='ماده ۳۰', limit=None)" in prompt


async def test_events_stream_in_order():
    provider = FakeProvider([_two_calls(), resp(text="پاسخ [1]")])
    kinds = []
    async for event in iter_with_tools(provider, None, "Question: x", system="sys", tools=fake_tools()):
        kinds.append(event["type"])
    assert kinds == ["round", "tool_call", "tool_result", "tool_call", "tool_result", "round", "answer", "done"]


def test_loop_mode_respects_env(monkeypatch):
    provider = FakeProvider([resp(text="x")])
    monkeypatch.setenv("TOOL_LOOP", "native")
    assert loop_mode(provider) == "native"
    monkeypatch.setenv("TOOL_LOOP", "text")
    assert loop_mode(provider) == "text"
    assert loop_mode(FakeTextProvider([resp(text="x")])) == "text"


def test_ledger_dedupes_and_renders():
    ledger = EvidenceLedger()
    assert ledger.add("law", "law-1", cite="مادهٔ ۳۰", title="جانشینی", text="متن") == 1
    assert ledger.add("law", "law-1", cite="مادهٔ ۳۰") == 1
    assert ledger.add("case", "case-9", cite="۱۴۰۲۰۰۹", title="پرونده") == 2
    rendered = ledger.render()
    assert rendered.splitlines()[0] == "[1] (ماده) مادهٔ ۳۰ — جانشینی"
    assert "[2] (پرونده) ۱۴۰۲۰۰۹ — پرونده" in rendered


def test_flatten_transcript_matches_legacy_shape():
    messages = [
        {"role": "user", "content": "Question: x"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "name": "search_law", "arguments": {"query": "q"}}]},
        {"role": "tool", "tool_call_id": "c1", "name": "search_law", "content": "[1] (ماده) الف"},
    ]
    flat = flatten_transcript(messages)
    assert flat == (
        "Question: x\n\nYou called tools and received:\n[search_law(query='q') →\n[1] (ماده) الف]"
        "\n\nUse these results. Call another tool only if you still need one."
    )

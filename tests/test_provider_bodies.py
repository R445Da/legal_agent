"""Request builders of the real providers — pure functions, no network."""

from app.llm.anthropic_provider import AnthropicProvider
from app.llm.base import strict_schema
from app.llm.groq_provider import GroqProvider
from app.llm.openai_provider import OpenAIProvider, transcript_messages

SPECS = [
    {"name": "search_cases", "description": "b", "strict": True,
     "parameters": {"type": "object", "properties": {"query": {"type": "string"},
                                                     "limit": {"type": ["integer", "null"]}},
                    "required": ["query"]}},
    {"name": "corpus_stats", "description": "a", "strict": True,
     "parameters": {"type": "object", "properties": {}}},
]

TRANSCRIPT = [
    {"role": "user", "content": "Question: x"},
    {"role": "assistant", "content": "", "reasoning": "hidden",
     "tool_calls": [{"id": "c1", "name": "search_cases", "arguments": {"query": "بازیافت", "limit": None}}],
     "turn": [{"type": "text", "text": ""}, {"type": "tool_use", "id": "c1", "name": "search_cases",
                                             "input": {"query": "بازیافت"}}]},
    {"role": "tool", "tool_call_id": "c1", "name": "search_cases", "content": "[1] (پرونده) ۱", "is_error": False},
    {"role": "tool", "tool_call_id": "c2", "name": "search_law", "content": "خطا", "is_error": True},
]


def test_strict_schema_requires_every_property():
    s = strict_schema(SPECS[0]["parameters"])
    assert s["additionalProperties"] is False and s["required"] == ["query", "limit"]
    assert strict_schema(None) == {"type": "object", "properties": {}, "additionalProperties": False, "required": []}


def test_anthropic_static_body_is_strict_sorted_and_cached():
    p = AnthropicProvider(model="claude-opus-5", api_key="k")
    body = p._static("SYS", 300, 0.0, False, SPECS, "auto", "low", None, True)
    assert [t["name"] for t in body["tools"]] == ["corpus_stats", "search_cases"]
    assert all(t["strict"] is True for t in body["tools"])
    assert body["tools"][1]["input_schema"]["additionalProperties"] is False
    assert body["tool_choice"] == {"type": "auto"}
    assert body["system"] == [{"type": "text", "text": "SYS", "cache_control": {"type": "ephemeral"}}]
    assert "temperature" not in body                       # opus-5 rejects sampling params
    assert body["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert body["output_config"] == {"effort": "low"}
    assert p._static("SYS", 300, 0.0, False, SPECS, "none", None, None, False)["tool_choice"] == {"type": "none"}
    assert p._static("SYS", 300, 0.0, False, None, "auto", None, None, False)["system"] == "SYS"


def test_anthropic_json_mode_and_schema():
    p = AnthropicProvider(model="claude-haiku-4-5", api_key="k")
    body = p._static("SYS", 100, 0.2, True, None, "auto", None, None, False)
    assert body["system"].endswith("Respond with JSON only — no prose, no code fences.")
    assert body["temperature"] == 0.2                        # haiku still takes it
    schema = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}
    body = p._static(None, 100, 0.0, False, None, "auto", None, schema, False)
    assert body["output_config"]["format"] == {"type": "json_schema", "schema": schema}


def test_anthropic_messages_replay_turn_and_group_tool_results():
    out = AnthropicProvider._messages(TRANSCRIPT, cache=True)
    assert out[0] == {"role": "user", "content": "Question: x"}
    assert out[1] == {"role": "assistant", "content": TRANSCRIPT[1]["turn"]}
    assert out[2]["role"] == "user" and len(out[2]["content"]) == 2
    first, second = out[2]["content"]
    assert first["type"] == "tool_result" and first["tool_use_id"] == "c1" and "is_error" not in first
    assert second["is_error"] is True and second["cache_control"] == {"type": "ephemeral"}
    # without `turn`, the assistant turn is rebuilt from the neutral fields
    rebuilt = AnthropicProvider._messages([TRANSCRIPT[0], {**TRANSCRIPT[1], "turn": None}], cache=False)
    assert rebuilt[1]["content"] == [{"type": "tool_use", "id": "c1", "name": "search_cases",
                                      "input": {"query": "بازیافت", "limit": None}}]


def test_openai_transcript_serialises_calls_and_drops_reasoning():
    msgs = transcript_messages("SYS", TRANSCRIPT)
    assert msgs[0] == {"role": "system", "content": "SYS"}
    assistant = msgs[2]
    assert assistant["content"] is None and "reasoning" not in assistant
    call = assistant["tool_calls"][0]
    assert call["type"] == "function" and call["function"]["arguments"] == '{"query": "بازیافت", "limit": null}'
    assert msgs[3] == {"role": "tool", "tool_call_id": "c1", "content": "[1] (پرونده) ۱"}
    assert msgs[4]["tool_call_id"] == "c2"


def test_openai_strict_functions_but_not_on_groq():
    openai_defs = OpenAIProvider(model="gpt-4.1", api_key="k")._tool_defs(SPECS)
    assert [d["function"]["name"] for d in openai_defs] == ["corpus_stats", "search_cases"]
    assert openai_defs[1]["function"]["strict"] is True
    assert openai_defs[1]["function"]["parameters"]["additionalProperties"] is False

    groq_defs = GroqProvider(model="openai/gpt-oss-20b", api_key="k")._tool_defs(SPECS)
    assert "strict" not in groq_defs[1]["function"]
    assert groq_defs[1]["function"]["parameters"] == SPECS[0]["parameters"]


def test_groq_body_uses_completion_cap_and_gates_effort():
    msgs = [{"role": "user", "content": "x"}]
    body = GroqProvider(model="openai/gpt-oss-20b", api_key="k")._body(msgs, 50, 0.0, False, SPECS, "none", "low", None)
    assert body["max_completion_tokens"] == 50 and "max_tokens" not in body
    assert body["tool_choice"] == "none" and body["reasoning_effort"] == "low"
    plain = OpenAIProvider(model="gpt-4.1", api_key="k")._body(msgs, 50, 0.0, True, None, "auto", None, None)
    assert plain["max_tokens"] == 50 and plain["response_format"] == {"type": "json_object"}
    assert "json" in plain["messages"][-1]["content"].lower()
    schema = {"type": "object", "properties": {}}
    with_schema = OpenAIProvider(model="gpt-4.1", api_key="k")._body(msgs, 50, 0.0, False, None, "auto", None, schema)
    assert with_schema["response_format"]["type"] == "json_schema"

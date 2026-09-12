"""
Defines the contract every LLM backend must implement.

Nothing else in the application should import a specific provider
(AnthropicProvider, OpenAIProvider, ...) directly. Code should only ever
depend on this abstract interface, obtained via the factory in factory.py.
That's what makes swapping models a config change instead of a rewrite.

Two calling shapes:

- `generate(prompt, ...)` — one user turn, one answer. Every provider has it.
- `chat(messages, ...)` — a *transcript*: user turns, assistant turns (with the
  tool calls they made) and tool results, replayed to the model so it can
  reason over what it already asked for. Providers with native tool-result
  turns (Anthropic, OpenAI, Groq) override it; everyone else inherits the
  default, which flattens the transcript to one prompt and calls `generate()`.
  `app/rag/tools.py` drives the loop and never needs to know which it got.

The provider-neutral transcript:

    {"role": "user",      "content": str}
    {"role": "assistant", "content": str, "tool_calls": [{id, name, arguments}] | None,
                          "turn": <provider-native message, replayed verbatim> | None}
    {"role": "tool",      "tool_call_id": str, "name": str, "content": str, "is_error": bool}
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class LLMResponse:
    text: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: float | None = None
    # Chain-of-thought from a reasoning model, when the backend returns it in
    # its own field (Groq gpt-oss/qwen3, DeepSeek-style `reasoning_content`).
    # None for plain chat models — callers use that to decide whether to render
    # a "thinking" panel at all.
    reasoning: str | None = None
    # Tool calls the model asked for, normalised to
    # [{"id": str, "name": str, "arguments": dict}]. None when `tools=` was not
    # passed or the model answered directly. `app/rag/tools.py` drives the loop.
    tool_calls: list[dict] | None = None
    raw: dict = field(default_factory=dict)  # provider-specific payload, for debugging/eval
    # Why the model stopped: end_turn | tool_use | max_tokens | stop | length | refusal.
    # Provider vocabularies differ; callers only compare against "tool_use".
    stop_reason: str | None = None
    # Prompt-cache accounting (Anthropic `cache_read_input_tokens` /
    # `cache_creation_input_tokens`, OpenAI `prompt_tokens_details.cached_tokens`).
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    # The assistant message exactly as the provider returned it (content
    # blocks, thinking signatures, tool_use ids). `chat()` replays it verbatim
    # on the next round; the neutral fields above are for everyone else.
    turn: list | dict | None = None


def strict_schema(schema: dict | None) -> dict:
    """The JSON schema a *strict* tool definition needs: no extra keys, every
    property required. Optional parameters are declared nullable in the tool
    spec (`{"type": ["integer", "null"]}`) so the model can still omit a value.
    Providers that support strict mode (Anthropic, OpenAI) apply this; the
    others send the schema as written."""
    out = dict(schema or {"type": "object", "properties": {}})
    props = dict(out.get("properties") or {})
    out["type"] = "object"
    out["properties"] = props
    out["additionalProperties"] = False
    out["required"] = list(props.keys())
    return out


def _fmt_args(args: dict | None) -> str:
    return ", ".join(f"{k}={v!r}" for k, v in (args or {}).items())


def flatten_transcript(messages: list[dict]) -> str:
    """One prompt out of a transcript, for providers without tool-result turns.

    Reproduces the shape the text loop has always sent — the user's prompt,
    then `You called tools and received:` blocks — so a rule-based provider
    (`mock`) and a small local model see exactly what they saw before.
    """
    parts: list[str] = []
    pending: list[str] = []
    args_by_id: dict[str, dict] = {}

    def flush() -> None:
        if pending:
            parts.append(
                "You called tools and received:\n" + "\n".join(pending)
                + "\n\nUse these results. Call another tool only if you still need one."
            )
            pending.clear()

    for message in messages:
        role = message.get("role")
        if role == "tool":
            args = args_by_id.get(str(message.get("tool_call_id")), {})
            pending.append(
                f"[{message.get('name', '?')}({_fmt_args(args)}) →\n{message.get('content', '')}]"
            )
            continue
        flush()
        if role == "assistant":
            for call in message.get("tool_calls") or []:
                args_by_id[str(call.get("id"))] = call.get("arguments") or {}
            if message.get("content"):
                parts.append(str(message["content"]))
        elif role == "user":
            parts.append(str(message.get("content", "")))
    flush()
    return "\n\n".join(p for p in parts if p)


class LLMProvider(ABC):
    """Common interface for any chat/completion-style LLM backend."""

    name: str  # short identifier, e.g. "anthropic", "openai", "local"

    # Capability flags — `chat()` replays tool results natively, `generate()`
    # honours `json_schema=`, the request can carry prompt-cache markers.
    supports_native_tools: bool = False
    supports_json_schema: bool = False
    supports_prompt_cache: bool = False

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        json_mode: bool = False,
        tools: list[dict] | None = None,
        tool_choice: str = "auto",
        **knobs,
    ) -> LLMResponse:
        """Run a single-turn generation and return a normalized response.

        json_mode=True asks the backend to emit strictly valid JSON (used by
        the orchestrator for intent routing and structured extraction).

        `tools` is a provider-neutral list of
        `{"name", "description", "parameters" (JSON schema), "strict"?}`. When
        the model asks to call one, `LLMResponse.tool_calls` is populated and
        `text` may be empty; `app/rag/tools.py` runs the dispatch loop.
        Mutually exclusive with `json_mode`. A provider that cannot do tools
        ignores the argument.

        `**knobs` carries model-specific tuning the caller discovered from
        `app.llm.knobs.knobs_for()` — e.g. `reasoning_effort="low"` on Groq
        gpt-oss. Every provider must accept and silently ignore knobs it does
        not support, so the UI can pass whatever the selected model advertises
        without the call site knowing which backend is behind it.
        """
        raise NotImplementedError

    async def chat(
        self,
        messages: list[dict],
        *,
        system: str | None = None,
        tools: list[dict] | None = None,
        tool_choice: str = "auto",
        max_tokens: int = 1024,
        temperature: float = 0.0,
        json_schema: dict | None = None,
        cache: bool = False,
        **knobs,
    ) -> LLMResponse:
        """Continue a transcript (see the module docstring for its shape).

        `tool_choice` is "auto" or "none" — "none" keeps the tool list in the
        request (so a cached prefix survives) but forbids another call.
        `cache=True` asks a provider that can to mark the system prompt and
        tool list for prompt caching; others ignore it.

        The default flattens the transcript and calls `generate()`, so a
        provider without native tool-result turns works everywhere the loop
        expects `chat()`.
        """
        if tool_choice == "none":
            tools = None
        return await self.generate(
            flatten_transcript(messages), system=system, max_tokens=max_tokens,
            temperature=temperature, tools=tools, tool_choice="auto",
            json_schema=json_schema, **knobs,
        )

    async def stream(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        **knobs,
    ):
        """Yield `{"type": "reasoning"|"answer", "delta": str}` as it generates.

        The default implementation simply runs `generate()` and emits the whole
        result in one or two pieces, so a backend that cannot stream still works
        everywhere a stream is expected. Providers that can stream override this
        and the chat page then fills in live.
        """
        response = await self.generate(
            prompt, system=system, max_tokens=max_tokens,
            temperature=temperature, **knobs,
        )
        if response.reasoning:
            yield {"type": "reasoning", "delta": response.reasoning}
        yield {"type": "answer", "delta": response.text}
        yield {"type": "done", "response": response}

    @abstractmethod
    def is_available(self) -> bool:
        """Cheap sanity check (e.g. API key present, endpoint reachable)."""
        raise NotImplementedError

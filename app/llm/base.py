"""
Defines the contract every LLM backend must implement.

Nothing else in the application should import a specific provider
(AnthropicProvider, OpenAIProvider, ...) directly. Code should only ever
depend on this abstract interface, obtained via the factory in factory.py.
That's what makes swapping models a config change instead of a rewrite.
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


class LLMProvider(ABC):
    """Common interface for any chat/completion-style LLM backend."""

    name: str  # short identifier, e.g. "anthropic", "openai", "local"

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
        `{"name", "description", "parameters" (JSON schema)}`. When the model
        asks to call one, `LLMResponse.tool_calls` is populated and `text` may
        be empty; `app/rag/tools.py` runs the dispatch loop. Mutually exclusive
        with `json_mode`. A provider that cannot do tools ignores the argument.

        `**knobs` carries model-specific tuning the caller discovered from
        `app.llm.knobs.knobs_for()` — e.g. `reasoning_effort="low"` on Groq
        gpt-oss. Every provider must accept and silently ignore knobs it does
        not support, so the UI can pass whatever the selected model advertises
        without the call site knowing which backend is behind it.
        """
        raise NotImplementedError

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

"""
Token accounting without touching the providers.

`MeteredProvider` wraps any `LLMProvider`, forwards every call unchanged, and
adds up what came back — calls, input/output tokens, prompt-cache hits and
wall-clock latency. The pipeline wraps the model once per step so each
`run_steps.payload` carries what that step cost; the tool loop sums its rounds
the same way for the provenance block.
"""

from dataclasses import dataclass, field

from .base import LLMProvider, LLMResponse

_FIELDS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")


@dataclass
class Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    latency_ms: float = 0.0
    models: list[str] = field(default_factory=list)

    def add(self, response: LLMResponse | None) -> None:
        if response is None:
            return
        self.calls += 1
        for name in _FIELDS:
            value = getattr(response, name, None)
            if value:
                setattr(self, name, getattr(self, name) + int(value))
        if response.latency_ms:
            self.latency_ms += float(response.latency_ms)
        if response.model and response.model not in self.models:
            self.models.append(response.model)

    def to_dict(self) -> dict:
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "latency_ms": round(self.latency_ms),
            "models": list(self.models),
        }


def usage_of(responses) -> dict:
    """The summed usage of a few responses, as the provenance block stores it."""
    total = Usage()
    for response in responses or []:
        total.add(response)
    return total.to_dict()


class MeteredProvider(LLMProvider):
    """A transparent wrapper: same provider, plus `.usage` and `.responses`."""

    def __init__(self, inner: LLMProvider):
        self.inner = inner
        self.usage = Usage()
        self.responses: list[LLMResponse] = []

    # The capability flags and every attribute the rest of the app reads
    # (`name`, `model`, `is_available`, ...) come from the wrapped provider.
    def __getattr__(self, item):
        return getattr(self.inner, item)

    @property
    def name(self) -> str:  # type: ignore[override]
        return self.inner.name

    @property
    def supports_native_tools(self) -> bool:  # type: ignore[override]
        return self.inner.supports_native_tools

    @property
    def supports_json_schema(self) -> bool:  # type: ignore[override]
        return self.inner.supports_json_schema

    @property
    def supports_prompt_cache(self) -> bool:  # type: ignore[override]
        return self.inner.supports_prompt_cache

    def is_available(self) -> bool:
        return self.inner.is_available()

    def _record(self, response: LLMResponse) -> LLMResponse:
        self.usage.add(response)
        self.responses.append(response)
        return response

    async def generate(self, prompt: str, **kwargs) -> LLMResponse:
        return self._record(await self.inner.generate(prompt, **kwargs))

    async def chat(self, messages: list[dict], **kwargs) -> LLMResponse:
        return self._record(await self.inner.chat(messages, **kwargs))

    async def stream(self, prompt: str, **kwargs):
        async for event in self.inner.stream(prompt, **kwargs):
            if event.get("type") == "done":
                self._record(event["response"])
            yield event

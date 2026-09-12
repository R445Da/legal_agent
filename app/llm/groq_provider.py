"""
Groq — an OpenAI-compatible endpoint with three deviations worth a subclass.

1. `max_tokens` is deprecated; the parameter that caps output is
   `max_completion_tokens`. It covers hidden reasoning tokens *and* the answer,
   so a small budget on a reasoning model is spent thinking and returns empty
   content with finish_reason="length".
2. Reasoning knobs are per-model, not per-provider: `reasoning_effort` is valid
   on gpt-oss and Qwen3 and a 400 on llama/allam/compound. See `knobs.py`.
3. The chain-of-thought comes back on `message.reasoning` rather than inside
   `content` — but only for gpt-oss (already split) and for other reasoners
   when asked for `reasoning_format="parsed"`.
4. With `json_mode`, Groq validates the completion against the JSON grammar
   *server-side*. When the reasoning budget eats the whole
   `max_completion_tokens` allowance, there is nothing left to validate and
   Groq raises `openai.BadRequestError` (code `json_validate_failed`,
   `failed_generation` empty) instead of returning a normal response with
   `finish_reason="length"` — so the length check below never gets a chance to
   fire. Caught here and turned into the same descriptive `RuntimeError`.

Everything else — client construction, JSON mode, usage accounting — is
inherited from OpenAIProvider.
"""

import os
import time

from .base import LLMResponse
from .knobs import _is_groq_reasoner
from .openai_provider import (
    OpenAIProvider, _normalise_tool_calls, ensure_json_hint, with_transient_retry,
)

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
# This key's /models does not list llama-3.3-70b-versatile; gpt-oss-20b is the
# fast, free, reasoning-capable default. Never assume a model exists — the
# registry builds the catalog from /models.
DEFAULT_MODEL = "openai/gpt-oss-20b"


class GroqProvider(OpenAIProvider):
    name = "groq"

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
    ):
        super().__init__(
            model=model or os.environ.get("GROQ_MODEL") or DEFAULT_MODEL,
            api_key=api_key or os.environ.get("GROQ_API_KEY"),
            base_url=base_url or os.environ.get("GROQ_BASE_URL") or GROQ_BASE_URL,
        )

    def _request(self, prompt, system, max_tokens, temperature, json_mode,
                 reasoning_effort, tools=None, tool_choice="auto"):
        """Groq's body: `max_completion_tokens` rather than `max_tokens`, and
        reasoning switches that are only legal on some models."""
        takes_effort, _ = _is_groq_reasoner(self.model)

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        body = {
            "model": self.model,
            "max_completion_tokens": max_tokens,  # not max_tokens — see docstring
            "temperature": temperature,
            "messages": messages,
        }
        if reasoning_effort and takes_effort:
            body["reasoning_effort"] = reasoning_effort
        if tools:
            body["tools"] = [
                {"type": "function", "function": {
                    "name": t["name"], "description": t.get("description", ""),
                    "parameters": t.get("parameters", {"type": "object", "properties": {}}),
                }}
                for t in tools
            ]
            body["tool_choice"] = tool_choice
        elif json_mode:
            body["response_format"] = {"type": "json_object"}
            # Groq 400s ("'messages' must contain the word 'json' in some
            # form") unless the prompt names JSON. Don't rely on the call site.
            body["messages"] = ensure_json_hint(messages)
        return body

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
        reasoning_effort: str | None = None,
        **_ignored,
    ) -> LLMResponse:
        import openai

        client = self._get_client()
        start = time.perf_counter()
        body = self._request(prompt, system, max_tokens, temperature, json_mode,
                             reasoning_effort, tools, tool_choice)
        try:
            resp = await with_transient_retry(
                lambda: client.chat.completions.create(**body), self.model
            )
        except openai.BadRequestError as e:
            if json_mode and e.code == "json_validate_failed":
                raise RuntimeError(
                    f"{self.model}: Groq's JSON-mode validator rejected the output "
                    f"(max_completion_tokens={max_tokens}) — the reasoning budget "
                    "likely consumed the whole allowance before any JSON was "
                    "produced. Raise max tokens, or lower reasoning effort."
                ) from e
            raise
        latency_ms = (time.perf_counter() - start) * 1000

        choice = (resp.choices or [None])[0]
        if choice is None:
            raise RuntimeError(f"{self.model}: Groq returned no choices")
        message = choice.message
        text = (message.content if message else None) or ""
        reasoning = getattr(message, "reasoning", None) if message else None
        tool_calls = _normalise_tool_calls(getattr(message, "tool_calls", None))

        if not text and not tool_calls and choice.finish_reason == "length":
            spent = resp.usage.completion_tokens if resp.usage else max_tokens
            raise RuntimeError(
                f"{self.model}: truncated at max_completion_tokens ({spent} tokens) "
                "before emitting any answer — the reasoning budget consumed the whole "
                "allowance. Raise max tokens, or lower reasoning effort."
            )

        return LLMResponse(
            text=text,
            model=self.model,
            input_tokens=resp.usage.prompt_tokens if resp.usage else None,
            output_tokens=resp.usage.completion_tokens if resp.usage else None,
            latency_ms=latency_ms,
            reasoning=reasoning,
            tool_calls=tool_calls or None,
            raw=resp.model_dump(),
        )

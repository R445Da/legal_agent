"""
Groq — an OpenAI-compatible endpoint with four deviations worth a subclass.

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

Strict function schemas are not accepted, and `json_schema` response formats
are accepted only on some models — a rejected schema falls back to plain
`json_object` once. Everything else — client construction, tool calls, the
multi-turn `chat()`, usage accounting — is inherited from OpenAIProvider.
"""

import os

from .knobs import _is_groq_reasoner
from .openai_provider import OpenAIProvider, ensure_json_hint

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
# This key's /models does not list llama-3.3-70b-versatile; gpt-oss-20b is the
# fast, free, reasoning-capable default. Never assume a model exists — the
# registry builds the catalog from /models.
DEFAULT_MODEL = "openai/gpt-oss-20b"


class GroqProvider(OpenAIProvider):
    name = "groq"
    _token_cap = "max_completion_tokens"  # not max_tokens — see docstring
    _strict_functions = False

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

    def _effort_ok(self) -> bool:
        takes_effort, _ = _is_groq_reasoner(self.model)
        return bool(takes_effort)

    async def _create(self, body: dict):
        import openai

        try:
            return await super()._create(body)
        except openai.BadRequestError as e:
            response_format = body.get("response_format") or {}
            if response_format.get("type") == "json_schema":
                # Not every Groq model takes a schema; the tolerant parser
                # downstream copes with plain JSON mode.
                fallback = {**body, "response_format": {"type": "json_object"},
                            "messages": ensure_json_hint(body["messages"])}
                return await super()._create(fallback)
            if response_format and e.code == "json_validate_failed":
                raise RuntimeError(
                    f"{self.model}: Groq's JSON-mode validator rejected the output "
                    f"(max_completion_tokens={body.get(self._token_cap)}) — the "
                    "reasoning budget likely consumed the whole allowance before any "
                    "JSON was produced. Raise max tokens, or lower reasoning effort."
                ) from e
            raise

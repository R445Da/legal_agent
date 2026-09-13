"""
Gemini, through Google's OpenAI-compatible layer.

`https://generativelanguage.googleapis.com/v1beta/openai` speaks the
`chat/completions` schema, so this is a thin subclass of `OpenAIProvider`
rather than a second HTTP client. Three differences are worth the file:

1. **It takes `max_tokens`**, not Groq's `max_completion_tokens` — so the base
   class's body is already right, and must not inherit Groq's override.
2. **`reasoning_effort` is not a parameter here.** Gemini controls thinking
   with its own `thinking_config`/`thinking_budget`, and the OpenAI shim
   rejects the unknown key rather than ignoring it — so it is dropped.
   `knobs.py` also stops offering the control for these ids.
3. **Parallel tool calls are switched off.** Gemini 3 signs each function call
   and refuses the following turn unless the signature is echoed back, but
   when it emits several calls in one message it signs only the first and then
   rejects the echo of "position 2" for having none. There is no signature to
   send, so the only way through is one call per hop. This costs an extra
   round trip on a multi-tool turn and is the difference between working and a
   hard 400.

Configured by `GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_BASE_URL` — the same
three names the accounting-agent demo uses, so one key serves both projects.
"""

import os

from .openai_provider import OpenAIProvider

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
DEFAULT_MODEL = "gemini-3.7-flash"

_GOOGLE_HOST = "generativelanguage.googleapis.com"


class GeminiProvider(OpenAIProvider):
    name = "gemini"

    def __init__(self, model: str | None = None, api_key: str | None = None,
                 base_url: str | None = None, **_):
        super().__init__(
            model=model or os.environ.get("GEMINI_MODEL") or DEFAULT_MODEL,
            api_key=api_key or os.environ.get("GEMINI_API_KEY"),
            base_url=(base_url or os.environ.get("GEMINI_BASE_URL")
                      or GEMINI_BASE_URL).rstrip("/"),
        )

    def is_available(self) -> bool:
        return bool(self.api_key)

    def _effort_ok(self) -> bool:
        """Gemini has no `reasoning_effort`.

        It controls thinking with its own `thinking_config`/`thinking_budget`,
        and the OpenAI shim rejects the unknown key rather than ignoring it —
        so the base class must not put it in the body. `knobs.py` also stops
        offering the control for these ids.
        """
        return False

    def _body(self, messages, max_tokens, temperature, json_mode, tools,
              tool_choice, reasoning_effort, json_schema) -> dict:
        body = super()._body(messages, max_tokens, temperature, json_mode, tools,
                             tool_choice, reasoning_effort, json_schema)
        if tools:
            # Gemini 3 signs each function call and refuses the following turn
            # unless the signature is echoed back — but when it emits several
            # calls in one message it signs only the first, then rejects the
            # echo of "position 2" for having none. There is no signature to
            # send for that call, so the only way through is one call per hop.
            body["parallel_tool_calls"] = False
        return body

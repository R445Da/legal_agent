"""
z.ai (Zhipu GLM), through its OpenAI-compatible endpoint.

`https://api.z.ai/api/paas/v4` speaks `chat/completions`, so like Gemini this
is a thin subclass. What it does not share with OpenAI is how thinking is
controlled: GLM takes a `thinking` object in the body —
`{"thinking": {"type": "enabled" | "disabled"}}` — and knows nothing about
`reasoning_effort`. Leaving thinking on doubles latency on a routing call that
only needs to emit six words of JSON, so `ZAI_THINKING` defaults to
`disabled` here, matching the accounting-agent demo's setting.

Configured by `ZAI_API_KEY`, `ZAI_MODEL`, `ZAI_BASE_URL`, `ZAI_THINKING`.
"""

import os

from .openai_provider import OpenAIProvider

ZAI_BASE_URL = "https://api.z.ai/api/paas/v4"
DEFAULT_MODEL = "glm-4.5-flash"


def _thinking() -> dict:
    mode = (os.environ.get("ZAI_THINKING") or "disabled").strip().lower()
    if mode not in {"enabled", "disabled"}:
        mode = "disabled"
    return {"type": mode}


class ZaiProvider(OpenAIProvider):
    name = "zai"

    def __init__(self, model: str | None = None, api_key: str | None = None,
                 base_url: str | None = None, **_):
        super().__init__(
            model=model or os.environ.get("ZAI_MODEL") or DEFAULT_MODEL,
            api_key=api_key or os.environ.get("ZAI_API_KEY"),
            base_url=(base_url or os.environ.get("ZAI_BASE_URL")
                      or ZAI_BASE_URL).rstrip("/"),
        )

    def is_available(self) -> bool:
        return bool(self.api_key)

    def _effort_ok(self) -> bool:
        """GLM knows nothing about `reasoning_effort`; it has `thinking`."""
        return False

    def _body(self, messages, max_tokens, temperature, json_mode, tools,
              tool_choice, reasoning_effort, json_schema) -> dict:
        body = super()._body(messages, max_tokens, temperature, json_mode, tools,
                             tool_choice, reasoning_effort, json_schema)
        # `thinking` is not in the OpenAI schema, and the SDK raises TypeError
        # on an unknown keyword rather than forwarding it — vendor fields have
        # to travel inside `extra_body`.
        body["extra_body"] = {**(body.get("extra_body") or {}), "thinking": _thinking()}
        return body

"""
Anthropic (Claude) — the direct API, no gateway in front of it.

Three things about the current Claude API drove this file's shape, and each one
is a 400 error if you get it wrong on a 4.6-or-later model:

1. **No assistant prefill.** The old trick for JSON mode — appending
   `{"role": "assistant", "content": "{"}` — is rejected outright. `json_mode`
   here appends a JSON instruction to the system prompt instead, which the
   orchestrator's tolerant `_parse_json` then reads. (A caller with a real
   schema should use `json_schema=` and get true structured output.)
2. **No sampling parameters.** `temperature` / `top_p` / `top_k` are rejected on
   Opus 5, Sonnet 5 and Opus 4.7/4.8. They are still accepted on Opus 4.6,
   Sonnet 4.6 and Haiku 4.5, so `_takes_temperature` gates it per model rather
   than dropping it everywhere.
3. **Thinking is configured, not budgeted.** `budget_tokens` is gone; the modern
   form is `thinking={"type": "adaptive"}` plus `output_config={"effort": ...}`.
   The app's existing `reasoning_effort` knob maps straight onto `effort`, and
   `display: "summarized"` is what fills `LLMResponse.reasoning` so the chat's
   «استدلال مدل» panel has something to show.

v3 adds the multi-turn `chat()`: assistant turns are replayed as the exact
content blocks Claude produced (thinking signatures and `tool_use` ids
included), every tool result goes back as a `tool_result` block in ONE user
message (parallel calls must be answered together), tools are sent `strict`
and sorted so the prefix is stable, and with `cache=True` the system prompt
and the newest tool results carry `cache_control` breakpoints.
"""

import os
import time

from .base import LLMProvider, LLMResponse, strict_schema

DEFAULT_MODEL = "claude-opus-5"

# Models that still accept sampling params. Everything newer rejects them.
_SAMPLING_OK = ("claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-5",
                "claude-3-5", "claude-3-7")

# Effort levels the current models accept. The UI knob only offers low/medium/
# high, but a caller may pass the wider set.
_EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")

_JSON_HINT = "Respond with JSON only — no prose, no code fences."

# `any` (forced tool use) is rejected by the newest models; the loop never
# asks for it, but a caller that does gets the closest legal value.
_TOOL_CHOICE = {"auto": "auto", "none": "none", "any": "any"}


def _takes_temperature(model: str) -> bool:
    return any(model.startswith(prefix) for prefix in _SAMPLING_OK)


class AnthropicProvider(LLMProvider):
    name = "anthropic"
    supports_native_tools = True
    supports_json_schema = True
    supports_prompt_cache = True

    def __init__(self, model: str | None = None, api_key: str | None = None):
        self.model = model or os.environ.get("ANTHROPIC_MODEL") or DEFAULT_MODEL
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self._client = None

    def _get_client(self):
        if self._client is None:
            import anthropic  # local import: only needed when this provider runs

            self._client = anthropic.AsyncAnthropic(api_key=self.api_key)
        return self._client

    def is_available(self) -> bool:
        return bool(self.api_key)

    # ---------------------------------------------------------------- request
    def _static(self, system, max_tokens, temperature, json_mode, tools,
                tool_choice, reasoning_effort, json_schema, cache) -> dict:
        """Everything in the request except `messages` — shared by generate(),
        chat() and stream(). Rendered in the order the API caches it:
        tools → system → messages, so one breakpoint on the system block
        caches the tool list too."""
        system_text = system or ""
        if json_mode and not tools and not json_schema and _JSON_HINT not in system_text:
            system_text = (system_text + "\n\n" + _JSON_HINT).strip()

        body: dict = {"model": self.model, "max_tokens": max_tokens}
        if system_text:
            if cache:
                body["system"] = [{"type": "text", "text": system_text,
                                   "cache_control": {"type": "ephemeral"}}]
            else:
                body["system"] = system_text
        if temperature is not None and _takes_temperature(self.model):
            body["temperature"] = temperature

        output_config: dict = {}
        if reasoning_effort in _EFFORT_LEVELS:
            output_config["effort"] = reasoning_effort
            # Effort only means something with thinking on; asking for the
            # summary is what gives the UI a reasoning trace to render.
            body["thinking"] = {"type": "adaptive", "display": "summarized"}
        # A real schema is the only correct way to force JSON on these models.
        if json_schema and not tools:
            output_config["format"] = {"type": "json_schema", "schema": json_schema}
        if output_config:
            body["output_config"] = output_config

        if tools:
            body["tools"] = [self._tool_def(t) for t in sorted(tools, key=lambda t: t["name"])]
            body["tool_choice"] = {"type": _TOOL_CHOICE.get(tool_choice, "auto")}
        return body

    @staticmethod
    def _tool_def(tool: dict) -> dict:
        params = tool.get("parameters", {"type": "object", "properties": {}})
        strict = bool(tool.get("strict", True))
        out = {"name": tool["name"], "description": tool.get("description", ""),
               "input_schema": strict_schema(params) if strict else params}
        if strict:
            out["strict"] = True
        return out

    @staticmethod
    def _messages(transcript: list[dict], cache: bool) -> list[dict]:
        """The neutral transcript as Claude message blocks."""
        out: list[dict] = []
        results: list[dict] = []

        def flush() -> None:
            if results:
                out.append({"role": "user", "content": list(results)})
                results.clear()

        for message in transcript:
            role = message.get("role")
            if role == "tool":
                block = {"type": "tool_result", "tool_use_id": str(message.get("tool_call_id")),
                         "content": str(message.get("content") or "")}
                if message.get("is_error"):
                    block["is_error"] = True
                results.append(block)
                continue
            flush()
            if role == "user":
                out.append({"role": "user", "content": str(message.get("content", ""))})
            elif role == "assistant":
                if message.get("turn"):
                    out.append({"role": "assistant", "content": message["turn"]})
                    continue
                blocks: list[dict] = []
                if message.get("content"):
                    blocks.append({"type": "text", "text": str(message["content"])})
                for call in message.get("tool_calls") or []:
                    blocks.append({"type": "tool_use", "id": str(call.get("id")),
                                   "name": call["name"], "input": call.get("arguments") or {}})
                if blocks:
                    out.append({"role": "assistant", "content": blocks})
        flush()

        # Second breakpoint: the newest tool results, so the next round re-reads
        # only what was added after them.
        if cache and out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
            last = dict(out[-1]["content"][-1])
            last["cache_control"] = {"type": "ephemeral"}
            out[-1]["content"][-1] = last
        return out

    @staticmethod
    def _collect(content) -> tuple[str, str, list[dict]]:
        """(answer text, thinking text, normalised tool calls) from the blocks."""
        text, thinking, calls = [], [], []
        for block in content or []:
            kind = getattr(block, "type", "")
            if kind == "text":
                text.append(block.text)
            elif kind == "thinking":
                thinking.append(getattr(block, "thinking", "") or "")
            elif kind == "tool_use":
                calls.append({"id": block.id, "name": block.name,
                              "arguments": block.input or {}})
        return "".join(text), "".join(thinking), calls

    def _translate(self, error: Exception) -> Exception:
        """Reword the failures that are easy to misread; pass anything else through.

        A zero credit balance arrives as a 400 `invalid_request_error` — the
        same class as a malformed body — so untranslated the UI just says
        "BadRequestError" and you go hunting for a bug in the request.
        """
        import anthropic

        if isinstance(error, anthropic.BadRequestError) and "credit balance" in str(error).lower():
            return RuntimeError(
                f"{self.model}: the Anthropic account has no credits. The key is "
                "valid — add credits under Plans & Billing at console.anthropic.com, "
                "or pick another model in the panel."
            )
        if isinstance(error, anthropic.AuthenticationError):
            return RuntimeError(
                f"{self.model}: ANTHROPIC_API_KEY was rejected (401). Check the key "
                "in .env, then run scripts/restart-ui.sh."
            )
        return error

    async def _send(self, call):
        try:
            return await call()
        except Exception as error:  # noqa: BLE001 — re-raised, only reworded
            raise self._translate(error) from error

    def _refusal(self, response) -> None:
        """`stop_reason == "refusal"` is an HTTP 200 with no usable content —
        check it before reading the blocks, or you get a silent empty answer."""
        if getattr(response, "stop_reason", None) != "refusal":
            return
        details = getattr(response, "stop_details", None)
        category = getattr(details, "category", None) or "unspecified"
        raise RuntimeError(
            f"{self.model}: the request was declined by a safety classifier "
            f"(category: {category}). Rephrase, or pick another model."
        )

    def _finish(self, response, start: float, max_tokens: int) -> LLMResponse:
        self._refusal(response)
        text, thinking, calls = self._collect(response.content)

        if not text and not calls and response.stop_reason == "max_tokens":
            raise RuntimeError(
                f"{self.model}: hit max_tokens ({max_tokens}) before writing an "
                "answer — thinking consumed the budget. Raise the output cap, or "
                "lower «میزان استدلال»."
            )

        usage = getattr(response, "usage", None)
        return LLMResponse(
            text=text,
            model=self.model,
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
            latency_ms=(time.perf_counter() - start) * 1000,
            reasoning=thinking or None,
            tool_calls=calls or None,
            raw=response.model_dump(),
            stop_reason=getattr(response, "stop_reason", None),
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", None),
            cache_write_tokens=getattr(usage, "cache_creation_input_tokens", None),
            turn=[block.model_dump(exclude_none=True) for block in (response.content or [])],
        )

    # --------------------------------------------------------------- generate
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
        json_schema: dict | None = None,
        cache: bool = False,
        **_ignored,
    ) -> LLMResponse:
        client = self._get_client()
        start = time.perf_counter()
        body = self._static(system, max_tokens, temperature, json_mode, tools,
                            tool_choice, reasoning_effort, json_schema, cache)
        body["messages"] = [{"role": "user", "content": prompt}]
        response = await self._send(lambda: client.messages.create(**body))
        return self._finish(response, start, max_tokens)

    # ------------------------------------------------------------------- chat
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
        json_mode: bool = False,
        reasoning_effort: str | None = None,
        **_ignored,
    ) -> LLMResponse:
        client = self._get_client()
        start = time.perf_counter()
        body = self._static(system, max_tokens, temperature, json_mode, tools,
                            tool_choice, reasoning_effort, json_schema, cache)
        body["messages"] = self._messages(messages, cache)
        response = await self._send(lambda: client.messages.create(**body))
        return self._finish(response, start, max_tokens)

    # ----------------------------------------------------------------- stream
    async def stream(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        json_mode: bool = False,
        reasoning_effort: str | None = None,
        json_schema: dict | None = None,
        **_ignored,
    ):
        """Yield reasoning and answer deltas as they arrive.

        Claude streams thinking and text as separate content blocks, so the
        chat can fill its «استدلال مدل» panel while the answer is still coming.
        """
        client = self._get_client()
        start = time.perf_counter()
        body = self._static(system, max_tokens, temperature, json_mode,
                            None, "auto", reasoning_effort, json_schema, False)
        body["messages"] = [{"role": "user", "content": prompt}]

        answer, thinking = [], []
        final = None
        # `messages.stream()` only issues the request on __aenter__, so the
        # translation has to wrap the whole block, not the constructor.
        try:
            async with client.messages.stream(**body) as stream:
                async for event in stream:
                    if event.type != "content_block_delta":
                        continue
                    delta = event.delta
                    if delta.type == "thinking_delta":
                        thinking.append(delta.thinking)
                        yield {"type": "reasoning", "delta": delta.thinking}
                    elif delta.type == "text_delta":
                        answer.append(delta.text)
                        yield {"type": "answer", "delta": delta.text}
                final = await stream.get_final_message()
        except Exception as error:  # noqa: BLE001 — re-raised, only reworded
            raise self._translate(error) from error

        self._refusal(final)
        usage = getattr(final, "usage", None)
        yield {
            "type": "done",
            "response": LLMResponse(
                text="".join(answer),
                model=self.model,
                input_tokens=getattr(usage, "input_tokens", None),
                output_tokens=getattr(usage, "output_tokens", None),
                latency_ms=(time.perf_counter() - start) * 1000,
                reasoning="".join(thinking) or None,
                raw={},
                stop_reason=getattr(final, "stop_reason", None),
                cache_read_tokens=getattr(usage, "cache_read_input_tokens", None),
                cache_write_tokens=getattr(usage, "cache_creation_input_tokens", None),
            ),
        }

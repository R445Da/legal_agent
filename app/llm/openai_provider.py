import asyncio
import json
import os
import time

from .base import LLMProvider, LLMResponse

# A hosted endpoint behind Cloudflare (Groq especially) geo-blocks some networks
# in *flapping* windows: the same key gets 403 "Access denied. Please check your
# network settings." one second and 200 the next. The OpenAI SDK raises that as
# `PermissionDeniedError`, which reads exactly like a bad key and has sent us
# chasing key rotations more than once. Retry it, then re-raise saying what it
# actually is.
_RETRIES = 3
_BACKOFF = (1.0, 3.0, 6.0)


async def with_transient_retry(call, model: str):
    """Await `call()`, retrying a transient 403 / 429 / 5xx / connection drop."""
    import openai

    last: Exception | None = None
    for attempt in range(_RETRIES):
        try:
            return await call()
        except (openai.PermissionDeniedError, openai.RateLimitError,
                openai.InternalServerError, openai.APIConnectionError) as error:
            last = error
            if attempt < _RETRIES - 1:
                await asyncio.sleep(_BACKOFF[attempt])

    if isinstance(last, openai.PermissionDeniedError):
        raise RuntimeError(
            f"{model}: the endpoint returned 403 «Access denied» {_RETRIES}× — that "
            "is the network/edge blocking this host, NOT a bad API key (a wrong key "
            "returns 401). It comes and goes: retry in a minute, use a VPN, or pick "
            "a local Ollama model in the model panel."
        ) from last
    raise last  # type: ignore[misc]


def ensure_json_hint(messages: list[dict]) -> list[dict]:
    """OpenAI and Groq both reject `response_format={"type":"json_object"}` with
    a 400 unless the word "json" appears somewhere in the messages:

        'messages' must contain the word 'json' in some form, to use
        'response_format' of type 'json_object'

    Every prompt in this app happens to say "Reply with JSON only", but a new
    caller that forgets gets an opaque 400 rather than a JSON response. Append
    the hint rather than trusting the call site to remember.
    """
    if any("json" in str(m.get("content", "")).lower() for m in messages):
        return messages
    patched = list(messages)
    patched[-1] = {**patched[-1],
                   "content": f"{patched[-1].get('content', '')}\n\nRespond with JSON only."}
    return patched


def _normalise_tool_calls(raw) -> list[dict]:
    """OpenAI/Groq return tool calls with `function.arguments` as a JSON string;
    normalise to `[{"id", "name", "arguments": dict}]`."""
    out = []
    for i, call in enumerate(raw or []):
        fn = getattr(call, "function", None)
        name = getattr(fn, "name", "") if fn else ""
        args = getattr(fn, "arguments", "") if fn else ""
        if isinstance(args, str):
            try:
                args = json.loads(args) if args else {}
            except json.JSONDecodeError:
                args = {}
        out.append({"id": getattr(call, "id", None) or f"call_{i}", "name": name,
                    "arguments": args if isinstance(args, dict) else {}})
    return out


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(
        self,
        model: str = "gpt-4.1",
        api_key: str | None = None,
        base_url: str | None = None,
    ):
        self.model = model
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        # Any OpenAI-compatible endpoint (Groq, Together, OpenRouter, a local
        # vLLM shim...). Leave unset to hit api.openai.com.
        self.base_url = base_url or os.environ.get("OPENAI_BASE_URL")
        self._client = None

    def _get_client(self):
        if self._client is None:
            import openai  # local import: don't require the package unless this provider is used
            self._client = openai.AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)
        return self._client

    def is_available(self) -> bool:
        return bool(self.api_key)

    def _request(self, prompt, system, max_tokens, temperature, json_mode, reasoning_effort):
        """The request body, shared by generate() and stream(). Subclasses
        override this where their API differs — Groq renames the token cap and
        adds per-model reasoning switches."""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        body = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
            body["messages"] = ensure_json_hint(messages)
        if reasoning_effort:
            body["reasoning_effort"] = reasoning_effort
        return body

    async def stream(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        json_mode: bool = False,
        reasoning_effort: str | None = None,
        **_ignored,
    ):
        """Emit answer and reasoning deltas as they arrive.

        Providers disagree on where the chain-of-thought lives on a delta —
        `reasoning` on Groq, `reasoning_content` DeepSeek-style — so check both.
        """
        client = self._get_client()
        start = time.perf_counter()
        body = self._request(prompt, system, max_tokens, temperature, json_mode, reasoning_effort)

        answer, thinking = [], []
        usage = None
        stream = await with_transient_retry(
            lambda: client.chat.completions.create(
                **body, stream=True, stream_options={"include_usage": True}
            ),
            self.model,
        )
        async for chunk in stream:
            if getattr(chunk, "usage", None):
                usage = chunk.usage
            for choice in chunk.choices or []:
                delta = choice.delta
                if delta is None:
                    continue
                thought = getattr(delta, "reasoning", None) or getattr(delta, "reasoning_content", None)
                if thought:
                    thinking.append(thought)
                    yield {"type": "reasoning", "delta": thought}
                if delta.content:
                    answer.append(delta.content)
                    yield {"type": "answer", "delta": delta.content}

        yield {
            "type": "done",
            "response": LLMResponse(
                text="".join(answer),
                model=self.model,
                input_tokens=getattr(usage, "prompt_tokens", None),
                output_tokens=getattr(usage, "completion_tokens", None),
                latency_ms=(time.perf_counter() - start) * 1000,
                reasoning="".join(thinking) or None,
                raw={},
            ),
        }

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
        client = self._get_client()
        start = time.perf_counter()

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        extra = {}
        if json_mode and not tools:
            extra["response_format"] = {"type": "json_object"}
            messages = ensure_json_hint(messages)
        if tools:
            extra["tools"] = [
                {"type": "function", "function": {
                    "name": t["name"], "description": t.get("description", ""),
                    "parameters": t.get("parameters", {"type": "object", "properties": {}}),
                }}
                for t in tools
            ]
            extra["tool_choice"] = tool_choice
        # A gateway may be fronting a reasoning model; pass the effort through
        # only when the caller asked for it (knobs.py decides whether the UI
        # even offers the control for this model id).
        if reasoning_effort:
            extra["reasoning_effort"] = reasoning_effort
        resp = await with_transient_retry(
            lambda: client.chat.completions.create(
                model=self.model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=messages,
                **extra,
            ),
            self.model,
        )

        latency_ms = (time.perf_counter() - start) * 1000

        # Gateways (9router's `combo`, content filters, routing failures) can
        # return a 200 with choices=null or an empty list — guard rather than
        # crash with a bare TypeError.
        choice = (resp.choices or [None])[0]
        if choice is None:
            raise RuntimeError(f"{self.model}: gateway returned no choices")
        message = choice.message
        text = (message.content if message else None) or ""

        tool_calls = _normalise_tool_calls(getattr(message, "tool_calls", None))

        if not text and not tool_calls and choice.finish_reason == "length":
            raise RuntimeError(
                f"{self.model}: response truncated at max_tokens before any text "
                "(reasoning model spent the whole budget thinking) — raise max_tokens"
            )

        # Reasoning gateways disagree on the field name; check both.
        reasoning = None
        if message is not None:
            reasoning = getattr(message, "reasoning", None) or getattr(
                message, "reasoning_content", None
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

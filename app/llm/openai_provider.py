import asyncio
import json
import os
import time

from .base import LLMProvider, LLMResponse, strict_schema

# A hosted endpoint behind Cloudflare (Groq especially) geo-blocks some networks
# in *flapping* windows: the same key gets 403 "Access denied. Please check your
# network settings." one second and 200 the next. The OpenAI SDK raises that as
# `PermissionDeniedError`, which reads exactly like a bad key and has sent us
# chasing key rotations more than once. Retry it, then re-raise saying what it
# actually is.
_RETRIES = 3
_BACKOFF = (1.0, 3.0, 6.0)

_TOOL_CHOICE = {"auto": "auto", "none": "none", "any": "required"}


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


def transcript_messages(system: str | None, transcript: list[dict]) -> list[dict]:
    """The neutral transcript as OpenAI chat messages.

    Assistant turns are rebuilt from `content` + `tool_calls` rather than
    replayed from `turn`: reasoning fields (`reasoning`, `reasoning_content`)
    must never be sent back — Groq rejects them.
    """
    messages: list[dict] = [{"role": "system", "content": system}] if system else []
    for message in transcript:
        role = message.get("role")
        if role == "user":
            messages.append({"role": "user", "content": str(message.get("content", ""))})
        elif role == "assistant":
            entry: dict = {"role": "assistant", "content": message.get("content") or None}
            calls = message.get("tool_calls") or []
            if calls:
                entry["tool_calls"] = [
                    {"id": str(c.get("id")), "type": "function",
                     "function": {"name": c["name"],
                                  "arguments": json.dumps(c.get("arguments") or {}, ensure_ascii=False)}}
                    for c in calls
                ]
            messages.append(entry)
        elif role == "tool":
            messages.append({"role": "tool", "tool_call_id": str(message.get("tool_call_id")),
                             "content": str(message.get("content") or "")})
    return messages


class OpenAIProvider(LLMProvider):
    name = "openai"
    supports_native_tools = True
    supports_json_schema = True
    # OpenAI caches long prefixes automatically; there is nothing to mark, but
    # `cache_read_tokens` is still reported when the endpoint returns it.
    supports_prompt_cache = False

    _token_cap = "max_tokens"       # Groq renames it
    _strict_functions = True        # Groq does not accept `strict`

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

    def _effort_ok(self) -> bool:
        """Whether `reasoning_effort` is legal for this model (Groq gates per model)."""
        return True

    def _tool_defs(self, tools: list[dict]) -> list[dict]:
        out = []
        for t in sorted(tools, key=lambda t: t["name"]):
            params = t.get("parameters", {"type": "object", "properties": {}})
            strict = self._strict_functions and bool(t.get("strict", True))
            fn = {"name": t["name"], "description": t.get("description", ""),
                  "parameters": strict_schema(params) if strict else params}
            if strict:
                fn["strict"] = True
            out.append({"type": "function", "function": fn})
        return out

    def _body(self, messages, max_tokens, temperature, json_mode, tools,
              tool_choice, reasoning_effort, json_schema) -> dict:
        """The request body, shared by generate(), chat() and stream()."""
        body = {
            "model": self.model,
            self._token_cap: max_tokens,
            "temperature": temperature,
            "messages": messages,
        }
        if tools:
            body["tools"] = self._tool_defs(tools)
            body["tool_choice"] = _TOOL_CHOICE.get(tool_choice, "auto")
        elif json_schema:
            body["response_format"] = {"type": "json_schema", "json_schema": {
                "name": "out", "schema": json_schema, "strict": True}}
            body["messages"] = ensure_json_hint(messages)
        elif json_mode:
            body["response_format"] = {"type": "json_object"}
            body["messages"] = ensure_json_hint(messages)
        # A gateway may be fronting a reasoning model; pass the effort through
        # only when the caller asked for it (knobs.py decides whether the UI
        # even offers the control for this model id).
        if reasoning_effort and self._effort_ok():
            body["reasoning_effort"] = reasoning_effort
        return body

    async def _create(self, body: dict):
        client = self._get_client()
        return await with_transient_retry(
            lambda: client.chat.completions.create(**body), self.model
        )

    def _parse(self, resp, start: float, max_tokens: int) -> LLMResponse:
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
            spent = resp.usage.completion_tokens if resp.usage else max_tokens
            raise RuntimeError(
                f"{self.model}: truncated at {self._token_cap} ({spent} tokens) before "
                "emitting any answer — a reasoning model spent the whole budget "
                "thinking. Raise max tokens, or lower reasoning effort."
            )

        # Reasoning gateways disagree on the field name; check both.
        reasoning = None
        if message is not None:
            reasoning = getattr(message, "reasoning", None) or getattr(
                message, "reasoning_content", None
            )
        usage = resp.usage
        details = getattr(usage, "prompt_tokens_details", None) if usage else None
        finish = choice.finish_reason
        return LLMResponse(
            text=text,
            model=self.model,
            input_tokens=usage.prompt_tokens if usage else None,
            output_tokens=usage.completion_tokens if usage else None,
            latency_ms=latency_ms,
            reasoning=reasoning,
            tool_calls=tool_calls or None,
            raw=resp.model_dump(),
            stop_reason="tool_use" if tool_calls else finish,
            cache_read_tokens=getattr(details, "cached_tokens", None) if details else None,
        )

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
        messages = ([{"role": "system", "content": system}] if system else []) + [
            {"role": "user", "content": prompt}]
        body = self._body(messages, max_tokens, temperature, json_mode, None, "auto",
                          reasoning_effort, None)

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

        details = getattr(usage, "prompt_tokens_details", None) if usage else None
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
                cache_read_tokens=getattr(details, "cached_tokens", None) if details else None,
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
        json_schema: dict | None = None,
        **_ignored,
    ) -> LLMResponse:
        start = time.perf_counter()
        messages = ([{"role": "system", "content": system}] if system else []) + [
            {"role": "user", "content": prompt}]
        body = self._body(messages, max_tokens, temperature, json_mode, tools,
                          tool_choice, reasoning_effort, json_schema)
        resp = await self._create(body)
        return self._parse(resp, start, max_tokens)

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
        start = time.perf_counter()
        body = self._body(transcript_messages(system, messages), max_tokens, temperature,
                          json_mode, tools, tool_choice, reasoning_effort, json_schema)
        resp = await self._create(body)
        return self._parse(resp, start, max_tokens)

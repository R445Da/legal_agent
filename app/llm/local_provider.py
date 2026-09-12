import json
import os
import time

import httpx

from .base import LLMProvider, LLMResponse


class LocalProvider(LLMProvider):
    """
    Talks to an OpenAI-compatible local server (Ollama, vLLM's OpenAI
    shim, LM Studio, etc). Swap base_url/model to point at whatever
    you're benchmarking (Qwen, Gemma, a fine-tuned legal model...).
    """

    name = "local"

    def __init__(
        self,
        model: str = "qwen2.5:14b",
        base_url: str | None = None,
    ):
        self.model = model
        self.base_url = base_url or os.environ.get("LOCAL_LLM_URL", "http://localhost:11434")

    def is_available(self) -> bool:
        try:
            r = httpx.get(f"{self.base_url}/api/tags", timeout=2.0)
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    def _payload(self, prompt, system, max_tokens, temperature, json_mode, stream):
        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": system or "",
            "stream": stream,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if json_mode:
            payload["format"] = "json"  # Ollama constrains output to valid JSON
        return payload

    async def stream(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        json_mode: bool = False,
        **_ignored,
    ):
        """Ollama streams newline-delimited JSON, one object per token."""
        start = time.perf_counter()
        text_parts: list[str] = []
        final: dict = {}

        payload = self._payload(prompt, system, max_tokens, temperature, json_mode, True)
        async with httpx.AsyncClient(timeout=300.0) as client:
            async with client.stream("POST", f"{self.base_url}/api/generate", json=payload) as r:
                r.raise_for_status()
                async for line in r.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    piece = chunk.get("response", "")
                    if piece:
                        text_parts.append(piece)
                        yield {"type": "answer", "delta": piece}
                    if chunk.get("done"):
                        final = chunk

        yield {
            "type": "done",
            "response": LLMResponse(
                text="".join(text_parts),
                model=self.model,
                input_tokens=final.get("prompt_eval_count"),
                output_tokens=final.get("eval_count"),
                latency_ms=(time.perf_counter() - start) * 1000,
                raw=final,
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
        **_ignored,  # cloud-only knobs (reasoning_effort, ...) are not errors here
    ) -> LLMResponse:
        if tools:
            return await self._generate_with_tools(
                prompt, system, max_tokens, temperature, tools
            )

        start = time.perf_counter()
        payload = self._payload(prompt, system, max_tokens, temperature, json_mode, False)

        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(f"{self.base_url}/api/generate", json=payload)
            r.raise_for_status()
            data = r.json()

        latency_ms = (time.perf_counter() - start) * 1000

        return LLMResponse(
            text=data.get("response", ""),
            model=self.model,
            input_tokens=data.get("prompt_eval_count"),
            output_tokens=data.get("eval_count"),
            latency_ms=latency_ms,
            raw=data,
        )

    async def _generate_with_tools(
        self, prompt, system, max_tokens, temperature, tools,
    ) -> LLMResponse:
        """Ollama exposes tool calling on `/api/chat` only, not `/api/generate`,
        so this is a separate path taken only when `tools=` is passed. The
        `/api/generate` path above (every non-tool call) is left untouched."""
        start = time.perf_counter()
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": self.model,
            "messages": messages,
            "tools": [
                {"type": "function", "function": {
                    "name": t["name"], "description": t.get("description", ""),
                    "parameters": t.get("parameters", {"type": "object", "properties": {}}),
                }}
                for t in tools
            ],
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(f"{self.base_url}/api/chat", json=payload)
            r.raise_for_status()
            data = r.json()

        message = data.get("message") or {}
        calls = []
        for i, call in enumerate(message.get("tool_calls") or []):
            fn = call.get("function") or {}
            args = fn.get("arguments")
            if isinstance(args, str):
                import json as _json
                try:
                    args = _json.loads(args)
                except _json.JSONDecodeError:
                    args = {}
            calls.append({"id": call.get("id") or f"call_{i}", "name": fn.get("name", ""),
                          "arguments": args or {}})

        return LLMResponse(
            text=message.get("content", "") or "",
            model=self.model,
            input_tokens=data.get("prompt_eval_count"),
            output_tokens=data.get("eval_count"),
            latency_ms=(time.perf_counter() - start) * 1000,
            tool_calls=calls or None,
            raw=data,
        )

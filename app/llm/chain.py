"""
One model id that means "try these in order, and end up on the local one".

Every hosted endpoint this project can reach fails in a different way, and none
of them fails rarely: Groq's API is geo-blocked from this network in flapping
windows, the Anthropic key has no credits, and the free Gemini and z.ai tiers
rate-limit a two-call agent turn. A single configured model therefore leaves
the whole app dead for reasons that have nothing to do with the app.

`ChainProvider` is the answer: an ordered list of providers, tried until one
answers, with the local Ollama model last. Because Ollama needs no key and no
network, the last link always works — slowly, on the CPU, but it works. That is
the difference between "the assistant is down" and "the assistant is thinking".

The order comes from `LLM_CHAIN` in `.env` (comma-separated registry ids), and
falls back to `_DEFAULT_CHAIN` below. A link that is missing its key is dropped
when the chain is built, not tried and failed at request time.

    LLM_CHAIN=gemini::gemini-3.7-flash,zai::glm-4.5-flash,local::qwen2.5:7b

What counts as "move to the next link" is deliberately broad — any exception.
A 429, a 403 from an edge, a gateway returning no choices, a model that turns
out not to support JSON mode: from the caller's point of view these are all
"this link cannot answer right now", and the point of the chain is to stop
caring which. The errors are collected and, if *every* link fails, raised
together so the real cause is still visible.

Streaming commits to the first link that produces a chunk: once a delta has
been yielded to the UI there is no honest way to start over on another model,
so failures after that point propagate.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time

from .base import LLMProvider, LLMResponse

log = logging.getLogger(__name__)

# Gemini Flash first (fast and free), z.ai's GLM Flash second, the local model
# last so the chain can always answer. Overridden by LLM_CHAIN.
_DEFAULT_CHAIN = (
    "gemini::gemini-3.7-flash",
    "zai::glm-4.5-flash",
    "local::qwen2.5:7b",
)

# Free tiers answer a burst of requests with 429 rather than queueing. Keep a
# small gap between calls to the same provider; the pipeline fires the router,
# the extractor and the answer back to back.
_MIN_INTERVAL_S = float(os.environ.get("LLM_MIN_INTERVAL_S", "0") or 0)
_last_call: dict[str, float] = {}

CHAIN_MODEL = "auto"

# How long a link that just failed is skipped for. Gemini's free tier is not a
# per-minute burst limit but a *daily* one — measured here as
# `GenerateRequestsPerDayPerProjectPerModel-FreeTier`, quotaValue 20 — so once
# it is spent, every later call pays another wasted round trip to learn the same
# thing. Parking the link for two minutes keeps a seven-step pipeline from
# paying that seven times, and is short enough that a genuinely transient
# failure (a dropped connection, one overloaded minute) is retried soon.
_COOLDOWN_S = float(os.environ.get("LLM_CHAIN_COOLDOWN_S", "120") or 120)
_cooling: dict[str, float] = {}


def _cool(model_id: str) -> None:
    _cooling[model_id] = time.monotonic() + _COOLDOWN_S


def _is_cooling(model_id: str) -> bool:
    until = _cooling.get(model_id)
    if until is None:
        return False
    if time.monotonic() >= until:
        del _cooling[model_id]
        return False
    return True


def chain_ids() -> list[str]:
    """The configured order, as registry ids."""
    raw = os.environ.get("LLM_CHAIN", "")
    ids = [part.strip() for part in raw.split(",") if part.strip()]
    return ids or list(_DEFAULT_CHAIN)


async def _pace(key: str) -> None:
    if _MIN_INTERVAL_S <= 0:
        return
    wait = _last_call.get(key, 0.0) + _MIN_INTERVAL_S - time.monotonic()
    if wait > 0:
        await asyncio.sleep(wait)
    _last_call[key] = time.monotonic()


class ChainProvider(LLMProvider):
    """Tries each link in turn. `model` is the id of whichever link answered."""

    name = "chain"

    def __init__(self, model: str | None = None, ids: list[str] | None = None, **_):
        self.model = model or CHAIN_MODEL
        self._ids = ids or chain_ids()
        self._links: list[tuple[str, LLMProvider]] | None = None

    # -- construction ------------------------------------------------------- #
    def links(self) -> list[tuple[str, LLMProvider]]:
        """`[(registry_id, provider)]` for every link that is configured.

        Built once and cached. A link whose provider reports `is_available()`
        False (no key) is dropped here rather than failing per request — except
        that the last link is always kept, so the chain is never empty.
        """
        if self._links is not None:
            return self._links

        from .registry import resolve  # late: registry imports this module

        built: list[tuple[str, LLMProvider]] = []
        for model_id in self._ids:
            try:
                provider = resolve(model_id)
            except Exception as error:  # noqa: BLE001 — an unknown id must not break the chain
                log.warning("chain: cannot build %s (%s)", model_id, error)
                continue
            if provider.is_available() or model_id == self._ids[-1]:
                built.append((model_id, provider))
        self._links = built
        return built

    def is_available(self) -> bool:
        return bool(self.links())

    def describe(self) -> str:
        return " → ".join(model_id for model_id, _ in self.links())

    # -- the two calls ------------------------------------------------------- #
    async def generate(self, prompt: str, **kwargs) -> LLMResponse:
        links = self.links()
        if not links:
            raise RuntimeError(
                "زنجیرهٔ مدل خالی است — هیچ‌یک از مدل‌های LLM_CHAIN قابل ساخت نبود."
            )

        failures: list[str] = []
        last = links[-1][0]
        for index, (model_id, provider) in enumerate(links):
            # The last link is never skipped: it is the one that has to answer.
            if _is_cooling(model_id) and model_id != last:
                continue
            await _pace(provider.name)
            try:
                response = await provider.generate(prompt, **kwargs)
            except Exception as error:  # noqa: BLE001 — that is the whole point
                failures.append(f"{model_id}: {type(error).__name__}: {str(error)[:180]}")
                log.warning("chain: %s failed (%s)", model_id, error)
                _cool(model_id)
                continue
            _cooling.pop(model_id, None)
            if index:
                log.info("chain: answered by %s after %d failure(s)", model_id, index)
            return response

        if not failures:
            # Everything was still cooling down and the last link was skipped
            # only because the list was empty — treat it as nothing configured.
            raise RuntimeError("هیچ مدلی در زنجیره قابل استفاده نبود.")
        raise RuntimeError(
            "هیچ مدلی پاسخ نداد — " + " | ".join(failures)
        )

    async def stream(self, prompt: str, **kwargs):
        """Stream from the first link that produces anything.

        A link is given up on only *before* its first chunk reaches the caller:
        after that the UI has already painted tokens, and silently restarting
        on another model would splice two different answers together.
        """
        links = self.links()
        if not links:
            raise RuntimeError(
                "زنجیرهٔ مدل خالی است — هیچ‌یک از مدل‌های LLM_CHAIN قابل ساخت نبود."
            )

        failures: list[str] = []
        last = links[-1][0]
        for model_id, provider in links:
            if _is_cooling(model_id) and model_id != last:
                continue
            await _pace(provider.name)
            agen = provider.stream(prompt, **kwargs)
            try:
                first = await agen.__anext__()
            except StopAsyncIteration:
                failures.append(f"{model_id}: خروجی خالی")
                continue
            except Exception as error:  # noqa: BLE001
                failures.append(f"{model_id}: {type(error).__name__}: {str(error)[:180]}")
                log.warning("chain: %s failed before first chunk (%s)", model_id, error)
                _cool(model_id)
                await agen.aclose()
                continue

            _cooling.pop(model_id, None)
            yield first
            async for chunk in agen:
                yield chunk
            return

        raise RuntimeError("هیچ مدلی پاسخ نداد — " + " | ".join(failures))

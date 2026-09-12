"""
The showcase model registry: every model the UI can switch to and compare —
local ones from Ollama, plus any number of OpenAI-compatible gateways (9router,
Groq, ...), plus direct Anthropic when a key is set.

A model is identified by an opaque id ``"<provider>::<model>"``. The ``::``
separator survives the colons in Ollama tags (``qwen2.5:3b``) and the slashes
in gateway names (``openai/gpt-oss-20b``), so the id can be round-tripped
through the ``model`` field on /ask, /assistant, /eval, /bench.

Two rules learned the hard way, both enforced here:

* **/models is authoritative.** Never inject a hardcoded default the gateway
  did not report — `llama-3.3-70b-versatile` 404s on send for keys whose
  /models omits it. A configured default is a fallback for when discovery
  returned *nothing at all*, not a guarantee.
* **Send a real User-Agent.** Groq sits behind Cloudflare, which answers the
  stdlib default agent with `HTTP 403: error code: 1010`.

Each catalog entry carries the tuning knobs its model accepts (see knobs.py),
so a UI can re-render its control panel from the selection alone.
"""

import json
import os
import shutil
import subprocess
import time
from dataclasses import asdict

import httpx
from dotenv import load_dotenv

load_dotenv()  # so the registry works even when imported before app.config

from .anthropic_provider import AnthropicProvider
from .base import LLMProvider
from .groq_provider import GROQ_BASE_URL, GroqProvider
from .knobs import knobs_for, reasoning_capable
from .local_provider import LocalProvider
from .openai_provider import OpenAIProvider

SEP = "::"

OLLAMA_NATIVE_DEFAULT = "http://localhost:11434"

# The gateway can report hundreds of models; show the curated ones first, then
# at most this many more so the dropdown stays usable.
_GATEWAY_EXTRA_LIMIT = 24

# Groq sits behind Cloudflare, which 403s ("error code: 1010") anything that
# looks like a script. httpx sends its own agent by default, but be explicit so
# the header survives any future refactor.
_USER_AGENT = "Mozilla/5.0 (legal-rag-workbench)"

# Speech / embedding / TTS / classifier ids that gateways return from /models
# alongside the chat LLMs — keep them out of the chat dropdown.
_NON_CHAT_HINTS = (
    "whisper", "tts", "-embed", "embedding", "playai-tts", "distil-whisper",
    "orpheus", "prompt-guard", "-guard-2",
)

# Friendly labels for ids worth surfacing first. Anything else a gateway
# reports is still selectable — it just sorts after these and keeps its raw id.
_CURATED = {
    "combo": "combo — auto-route",
    "anthropic/claude-sonnet-4-20250514": "Claude Sonnet 4",
    "anthropic/claude-opus-4-20250514": "Claude Opus 4",
    "anthropic/claude-3-5-sonnet-20241022": "Claude 3.5 Sonnet",
    "openai/gpt-4.1": "GPT-4.1",
    "openai/gpt-4o": "GPT-4o",
    "openai/gpt-oss-120b": "GPT-OSS 120B — reasoning",
    "openai/gpt-oss-20b": "GPT-OSS 20B — reasoning, fast",
    "groq/compound": "Compound",
    "groq/compound-mini": "Compound mini — fastest",
}

# Direct Anthropic models. Ids are exact and complete — never append a date
# suffix. Opus 5 first: it is the default and the most capable.
_DIRECT_ANTHROPIC = [
    ("claude-opus-5", "Claude Opus 5"),
    ("claude-sonnet-5", "Claude Sonnet 5"),
    ("claude-haiku-4-5", "Claude Haiku 4.5"),
]

_PROVIDER_DEFAULT_MODEL = {
    "anthropic": "claude-opus-5",
    "openai": "gpt-4.1",
    "groq": "openai/gpt-oss-20b",
    "local": "qwen2.5:3b",
}


def make_id(provider: str, model: str) -> str:
    return f"{provider}{SEP}{model}"


def split_id(model_id: str) -> tuple[str, str]:
    """('local', 'qwen2.5:3b'). A bare model name (no SEP) is assumed to
    belong to the provider named in LLM_PROVIDER."""
    if SEP in model_id:
        provider, model = model_id.split(SEP, 1)
        return provider, model
    return os.environ.get("LLM_PROVIDER", "local"), model_id


def _looks_non_chat(model_id: str) -> bool:
    lowered = model_id.lower()
    return any(hint in lowered for hint in _NON_CHAT_HINTS)


def _get_json(
    url: str, *, key: str | None = None, timeout: float = 4.0,
    headers: dict | None = None,
) -> dict:
    """`key` sends an OpenAI-style bearer token; `headers` is for providers with
    their own scheme (Anthropic authenticates with `x-api-key`)."""
    headers = {"User-Agent": _USER_AGENT, **(headers or {})}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    # Groq's Cloudflare edge geo-blocks this network in flapping ~1-2 min
    # windows — a 403 one moment, 200 the next. One quick retry turns most of
    # those flaps into a hit instead of caching the provider as dead for the
    # whole `_catalog` TTL.
    last: Exception | None = None
    for attempt in range(2):
        try:
            r = httpx.get(url, headers=headers, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPStatusError as error:
            last = error
            if error.response.status_code not in (403, 429, 502, 503):
                raise
            time.sleep(1.0)
    raise last  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# Ollama: find the binary, start it, list and pull models
# --------------------------------------------------------------------------- #
def find_ollama_binary() -> str | None:
    """Mirror `scripts/serve.sh`: honour $OLLAMA_BIN, then the tarball location
    ~/ollama/bin/ollama, then whatever is on PATH."""
    for candidate in (os.environ.get("OLLAMA_BIN"), os.path.expanduser("~/ollama/bin/ollama")):
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return shutil.which("ollama")


def _ollama_base() -> str:
    return os.environ.get("LOCAL_LLM_URL", OLLAMA_NATIVE_DEFAULT).rstrip("/")


def _is_local_host(base: str) -> bool:
    """True when `base` is this machine. Only then can we start or pull with the
    CLI — a remote Ollama (the compose service, a LAN box) is somebody else's
    process and has to be driven over HTTP."""
    return "://localhost" in base or "://127.0.0.1" in base


def ollama_running(base: str | None = None) -> bool:
    try:
        _get_json(f"{base or _ollama_base()}/api/version", timeout=2.0)
        return True
    except (httpx.HTTPError, ValueError):
        return False


def start_ollama(base: str | None = None, *, wait_seconds: float = 20.0) -> None:
    """Start `ollama serve` in the background and block until it answers.
    Raises RuntimeError if the binary is missing or it never comes up."""
    base = base or _ollama_base()
    if ollama_running(base):
        return
    if not _is_local_host(base):
        raise RuntimeError(
            f"Ollama at {base} is not this machine — start it there "
            "(or `docker compose --profile local up ollama`); we cannot spawn it."
        )
    binary = find_ollama_binary()
    if not binary:
        raise RuntimeError(
            "Ollama is not installed or not on PATH (looked at $OLLAMA_BIN, "
            "~/ollama/bin/ollama, and PATH)."
        )
    try:
        subprocess.Popen(
            [binary, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as error:
        raise RuntimeError(f"could not launch `{binary} serve`: {error}") from error

    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if ollama_running(base):
            return
        time.sleep(0.5)
    raise RuntimeError(f"Ollama did not become ready on {base} within {wait_seconds:.0f}s.")


def ensure_ollama(base: str | None = None, *, autostart: bool = True) -> bool:
    """True if Ollama is reachable, starting it first when autostart is set.
    Never raises — callers check the bool."""
    base = base or _ollama_base()
    if ollama_running(base):
        return True
    if not autostart:
        return False
    try:
        start_ollama(base)
        return True
    except RuntimeError:
        return False


def list_ollama_models(base: str | None = None) -> list[str]:
    try:
        data = _get_json(f"{base or _ollama_base()}/api/tags", timeout=3.0)
    except (httpx.HTTPError, ValueError):
        return []
    return sorted(m["name"] for m in data.get("models", []) if m.get("name"))


def pull_ollama_model(model: str, *, timeout: float = 1800) -> None:
    """Download `model`. Uses the Ollama CLI when the server is local, and the
    server's own /api/pull endpoint when it is not — inside the container there
    is no binary, only a sibling service."""
    base = _ollama_base()
    ensure_ollama(base)
    binary = find_ollama_binary() if _is_local_host(base) else None
    if not binary:
        _pull_over_http(model, base=base, timeout=timeout)
        return
    result = subprocess.run(
        [binary, "pull", model], capture_output=True, text=True, timeout=timeout, check=False
    )
    if result.returncode != 0:
        details = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"`ollama pull {model}` failed: {details[-300:]}")


def _pull_over_http(model: str, *, base: str, timeout: float) -> None:
    """POST /api/pull against a remote Ollama. It streams newline-delimited JSON
    status objects; we drain them and check the last one."""
    last = ""
    try:
        with httpx.stream(
            "POST",
            f"{base}/api/pull",
            json={"model": model, "stream": True},
            timeout=timeout,
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                line = line.strip()
                if not line:
                    continue
                last = line
                try:
                    status = json.loads(line)
                except ValueError:
                    continue
                if status.get("error"):
                    raise RuntimeError(f"pull of `{model}` failed: {status['error']}")
    except httpx.HTTPError as error:
        raise RuntimeError(f"pull of `{model}` failed against {base}: {error}") from error
    if '"status":"success"' not in last.replace(" ", ""):
        raise RuntimeError(f"pull of `{model}` did not report success (last: {last[:200]})")


# --------------------------------------------------------------------------- #
# Catalog
# --------------------------------------------------------------------------- #
def _entry(provider: str, model: str, label: str, *, available: bool, reason: str = "") -> dict:
    return {
        "id": make_id(provider, model),
        "label": label,
        "provider": provider,
        "model": model,
        "available": available,
        "reason": reason,
        "reasoning": reasoning_capable(provider, model),
        "knobs": [asdict(k) for k in knobs_for(provider, model)],
    }


def _local_models(autostart: bool = False) -> list[dict]:
    if not ensure_ollama(autostart=autostart):
        return []
    return [
        _entry("local", tag, f"{tag}  ·  local", available=True)
        for tag in list_ollama_models()
    ]


def gateways() -> list[dict]:
    """Every configured OpenAI-compatible gateway. A gateway with no key is
    still listed (marked unavailable) so the UI can explain what is missing."""
    out = []
    base = os.environ.get("OPENAI_BASE_URL")
    if base:
        out.append({
            "provider": "openai",
            "label": "9router",
            "base_url": base.rstrip("/"),
            "key": os.environ.get("OPENAI_API_KEY"),
        })
    if os.environ.get("GROQ_API_KEY") or os.environ.get("GROQ_BASE_URL"):
        out.append({
            "provider": "groq",
            "label": "Groq",
            "base_url": (os.environ.get("GROQ_BASE_URL") or GROQ_BASE_URL).rstrip("/"),
            "key": os.environ.get("GROQ_API_KEY"),
        })
    return out


def _gateway_models(gw: dict) -> list[dict]:
    provider, label, base, key = gw["provider"], gw["label"], gw["base_url"], gw["key"]

    if not key:
        fallback = _PROVIDER_DEFAULT_MODEL.get(provider, "")
        return [_entry(provider, fallback, f"{fallback}  ·  {label}", available=False,
                       reason=f"no API key configured for {label}")] if fallback else []

    try:
        data = _get_json(f"{base}/models", key=key)
        ids = [m["id"] for m in data.get("data", []) if m.get("id")]
    except (httpx.HTTPError, ValueError) as error:
        # Keep the gateway visible with the reason rather than vanishing.
        fallback = _PROVIDER_DEFAULT_MODEL.get(provider, "")
        reason = f"{label} /models unreachable: {type(error).__name__}: {str(error)[:120]}"
        return [_entry(provider, fallback, f"{fallback}  ·  {label}", available=False,
                       reason=reason)] if fallback else []

    ids = [m for m in ids if not _looks_non_chat(m)]
    # /models is authoritative: curated ids only appear if the gateway reported
    # them. Everything else follows, capped so the dropdown stays usable.
    curated = [m for m in ids if m in _CURATED]
    extras = sorted(set(ids) - set(curated))[:_GATEWAY_EXTRA_LIMIT]

    return [
        _entry(provider, m, f"{_CURATED.get(m, m)}  ·  {label}", available=True)
        for m in curated + extras
    ]


ANTHROPIC_BASE_URL = "https://api.anthropic.com/v1"


def _anthropic_models() -> list[dict]:
    """Ask Anthropic what this key can actually see.

    Same rule as the gateways: /models is authoritative. It also costs nothing
    and works with a zero credit balance, so the dropdown reflects the real
    account (including models released after this file was written) instead of
    a hardcoded list. `_DIRECT_ANTHROPIC` is only the ordering/label hint and
    the fallback for when discovery returns nothing.
    """
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return []

    labels = dict(_DIRECT_ANTHROPIC)
    preferred = [m for m, _ in _DIRECT_ANTHROPIC]
    try:
        data = _get_json(
            f"{ANTHROPIC_BASE_URL}/models",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
        )
    except (httpx.HTTPError, ValueError) as error:
        reason = f"Anthropic /models unreachable: {type(error).__name__}: {str(error)[:110]}"
        return [
            _entry("anthropic", m, f"{label}  ·  Anthropic", available=False, reason=reason)
            for m, label in _DIRECT_ANTHROPIC
        ]

    found = {
        m["id"]: m.get("display_name") or m["id"]
        for m in (data.get("data") or []) if m.get("id")
    }
    if not found:
        found = dict(_DIRECT_ANTHROPIC)

    # Curated ids first, in order; then everything else the key can reach.
    ordered = [m for m in preferred if m in found] + sorted(
        m for m in found if m not in preferred
    )
    return [
        _entry("anthropic", m, f"{labels.get(m) or found[m]}  ·  Anthropic", available=True)
        for m in ordered
    ]


def catalog(autostart_ollama: bool = False) -> list[dict]:
    """Every model the UI can pick: local first, then each gateway, then direct
    Anthropic. Entries carry `available`, a `reason` when not, and the `knobs`
    that model accepts."""
    entries = _local_models(autostart=autostart_ollama)
    for gw in gateways():
        entries += _gateway_models(gw)
    return entries + _anthropic_models()


def notes(entries: list[dict]) -> list[str]:
    """Human-readable reasons for every unavailable entry, de-duplicated —
    the UI's 'Connection notes' panel."""
    seen, out = set(), []
    for e in entries:
        if not e["available"] and e["reason"] and e["reason"] not in seen:
            seen.add(e["reason"])
            out.append(e["reason"])
    return out


def default_id() -> str:
    """The model id the server boots with, from LLM_PROVIDER / LLM_MODEL."""
    provider = os.environ.get("LLM_PROVIDER", "local")
    model = os.environ.get("LLM_MODEL") or _PROVIDER_DEFAULT_MODEL.get(provider, "")
    return make_id(provider, model)


def resolve(model_id: str) -> LLMProvider:
    """Build the LLMProvider for a registry id (or a bare model name)."""
    provider, model = split_id(model_id)
    if provider == "local":
        return LocalProvider(model=model)
    if provider == "anthropic":
        return AnthropicProvider(model=model)
    if provider == "groq":
        return GroqProvider(model=model)
    if provider == "openai":
        return OpenAIProvider(model=model)
    raise ValueError(f"unknown provider {provider!r} in model id {model_id!r}")

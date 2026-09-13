"""
Speech to text, in whichever way is available.

The assistant's mic button records audio in the browser; the text is dropped
into the composer so a court session can be dictated instead of typed. Three
backends, best first:

* **Gemini's live transcription model** (`app/rag/gemini_stt.py`) — the default
  whenever `GEMINI_API_KEY` is set. It is the only one that takes a Persian
  legal `custom_vocabulary`, which is what keeps «کلاسه» from coming back as
  «کلاس», and it is the same path `scripts/live.sh --mic` uses.
* **Groq's hosted Whisper** — fast, but the API is geo-blocked from this
  network in flapping windows.
* **faster-whisper on the CPU** — no key, no network, slow. The floor, not the
  default: it is what answers when nothing else can.

Model size for the local one via WHISPER_MODEL (tiny | base | small | medium |
large-v3). Set STT=0 to disable the microphone entirely.
"""

import asyncio
import functools
import os
import tempfile

_ENABLED = os.environ.get("STT", "1") != "0"
_SIZE = os.environ.get("WHISPER_MODEL", "small")
_LANG = os.environ.get("WHISPER_LANG", "fa")


def enabled() -> bool:
    return _ENABLED


@functools.lru_cache(maxsize=3)
def _model(size: str | None = None):
    from faster_whisper import WhisperModel

    return WhisperModel(size or _SIZE, device="cpu", compute_type="int8")


def _run(audio_bytes: bytes, suffix: str, size: str | None = None) -> dict:
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as f:
        f.write(audio_bytes)
        f.flush()
        segments, info = _model(size).transcribe(
            f.name, language=_LANG, vad_filter=True, beam_size=1
        )
        text = " ".join(s.text.strip() for s in segments).strip()
    return {
        "text": text,
        "language": info.language,
        "duration": round(info.duration, 1),
        "model": f"faster-whisper-{size or _SIZE}",
    }


def _gemini_models() -> list[tuple[str, str]]:
    """Gemini's live transcription, when a key is configured and the SDK is
    installed. First in the list because it is the only backend that can be
    biased toward this archive's vocabulary."""
    from app.rag import gemini_stt

    if not gemini_stt.available():
        return []
    return [("gemini:" + gemini_stt.model(),
             f"{gemini_stt.model()} · Gemini — واژگان حقوقی")]


def _groq_models() -> list[tuple[str, str]]:
    """Groq's hosted Whisper, when a key is configured. `large-v3-turbo` is much
    faster and more accurate on Persian than a `medium` model on this CPU, which
    is why it is the default whenever a key exists."""
    if not os.environ.get("GROQ_API_KEY"):
        return []
    return [
        ("groq:whisper-large-v3-turbo", "Whisper large-v3 turbo · Groq — سریع‌ترین"),
        ("groq:whisper-large-v3", "Whisper large-v3 · Groq — دقیق‌ترین"),
    ]


def choices() -> list[tuple[str, str]]:
    """Every transcription backend available right now, best first."""
    local = [
        (f"local:{size}", f"faster-whisper {size} · محلی")
        for size in ("large-v3", "medium", "small", "base", "tiny")
    ]
    return _gemini_models() + _groq_models() + local


def default_choice() -> str:
    for backend in (_gemini_models(), _groq_models()):
        if backend:
            return backend[0][0]
    return f"local:{_SIZE}"


async def _groq_transcribe(audio_bytes: bytes, filename: str, model: str) -> dict:
    """Groq's OpenAI-compatible /audio/transcriptions."""
    import openai

    client = openai.AsyncOpenAI(
        api_key=os.environ.get("GROQ_API_KEY"),
        base_url=os.environ.get("GROQ_BASE_URL") or "https://api.groq.com/openai/v1",
    )
    result = await client.audio.transcriptions.create(
        file=(filename, audio_bytes),
        model=model,
        language=_LANG or None,
    )
    return {"text": (result.text or "").strip(), "language": _LANG, "model": f"groq/{model}"}


async def transcribe(
    audio_bytes: bytes, filename: str = "audio.webm", *, choice: str | None = None
) -> dict:
    """Transcribe with the chosen backend — `groq:<model>` or `local:<size>`."""
    if not _ENABLED:
        raise RuntimeError("speech-to-text is disabled (STT=0)")

    choice = choice or default_choice()
    backend, _, name = choice.partition(":")

    if backend == "gemini":
        from app.rag import gemini_stt

        return await gemini_stt.transcribe(audio_bytes)
    if backend == "groq":
        return await _groq_transcribe(audio_bytes, filename or "audio.wav", name)

    suffix = os.path.splitext(filename)[1] or ".webm"
    return await asyncio.to_thread(_run, audio_bytes, suffix, name or _SIZE)


async def stream(
    audio_bytes: bytes, filename: str = "audio.webm", *, choice: str | None = None
):
    """Transcribe as the model hears it, yielding as it goes.

    Same event shape for every backend — `{"type": "interim"|"final"|"done",
    "text": ...}` — so the composer has one code path and does not care which
    one answered.

    Only Gemini's live model actually streams. Groq and faster-whisper take a
    finished recording and hand back a finished string, so they emit a single
    `done`: the words appear at the end rather than as they are spoken, which
    is the honest behaviour for a backend that cannot do better, not a bug to
    paper over with a fake typewriter effect.
    """
    if not _ENABLED:
        raise RuntimeError("speech-to-text is disabled (STT=0)")

    choice = choice or default_choice()
    backend, _, name = choice.partition(":")

    if backend == "gemini":
        from app.rag import gemini_stt

        frames = gemini_stt.to_pcm16(audio_bytes)
        async for event in gemini_stt.stream(frames):
            yield event
        return

    result = await transcribe(audio_bytes, filename, choice=choice)
    yield {"type": "done", "text": (result or {}).get("text", ""),
           "model": (result or {}).get("model")}

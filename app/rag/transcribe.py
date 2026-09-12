"""
Speech-to-text with faster-whisper (CTranslate2, local, CPU, no API).

The assistant's mic button records audio in the browser and POSTs it to
`/transcribe`; the text is dropped into the composer so you can dictate a court
session instead of typing it. Fully offline once the model is downloaded.

Model size via WHISPER_MODEL (tiny | base | small | medium | large-v3),
default "small" — a reasonable Persian/CPU balance. Set STT=0 to disable.
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
    return _groq_models() + local


def default_choice() -> str:
    groq = _groq_models()
    return groq[0][0] if groq else f"local:{_SIZE}"


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

    if backend == "groq":
        return await _groq_transcribe(audio_bytes, filename or "audio.wav", name)

    suffix = os.path.splitext(filename)[1] or ".webm"
    return await asyncio.to_thread(_run, audio_bytes, suffix, name or _SIZE)

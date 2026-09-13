"""`transcribe.stream` — one event shape whichever backend answers.

The composer renders the transcript as it arrives, so it needs a single code
path. Gemini's live model really streams; Groq and faster-whisper take a
finished recording and return a finished string, and for those the honest
behaviour is one `done` at the end rather than a fake typewriter effect. Both
must come back through the same generator so the UI never branches on backend.
"""

import pytest

from app.rag import transcribe


async def _drain(agen) -> list[dict]:
    return [event async for event in agen]


async def test_a_non_streaming_backend_still_yields_one_done(monkeypatch):
    async def fake(audio_bytes, filename="audio.webm", *, choice=None):
        return {"text": "متن کامل", "model": "whisper-fake"}

    monkeypatch.setattr(transcribe, "transcribe", fake)
    monkeypatch.setattr(transcribe, "_ENABLED", True)

    events = await _drain(transcribe.stream(b"audio", "a.wav", choice="local:base"))

    assert [e["type"] for e in events] == ["done"]
    assert events[0]["text"] == "متن کامل"


async def test_the_gemini_backend_passes_its_events_through(monkeypatch):
    """Interim phrases have to reach the caller — they are the whole point."""
    from app.rag import gemini_stt

    async def fake_stream(frames, *, timeout_s=None):
        yield {"type": "interim", "text": "وضعیت"}
        yield {"type": "interim", "text": "وضعیت مالی شرکت"}
        yield {"type": "final", "text": "وضعیت مالی شرکت چطور است؟"}
        yield {"type": "done", "text": "وضعیت مالی شرکت چطور است؟", "model": "live"}

    monkeypatch.setattr(gemini_stt, "stream", fake_stream)
    monkeypatch.setattr(gemini_stt, "to_pcm16", lambda raw: raw)
    monkeypatch.setattr(transcribe, "_ENABLED", True)

    events = await _drain(transcribe.stream(b"audio", "a.wav", choice="gemini:live"))

    assert [e["type"] for e in events] == ["interim", "interim", "final", "done"]
    assert events[-1]["text"] == "وضعیت مالی شرکت چطور است؟"


async def test_streaming_is_refused_when_speech_is_switched_off(monkeypatch):
    monkeypatch.setattr(transcribe, "_ENABLED", False)
    with pytest.raises(RuntimeError):
        await _drain(transcribe.stream(b"audio", "a.wav"))


def test_the_composer_consumes_the_stream_rather_than_the_one_shot_call():
    """A regression guard with a short history: the mic path used to call
    `stt.transcribe()` behind a spinner and throw every interim event away,
    so the streaming backend that was already here was invisible in the UI."""
    import pathlib

    source = pathlib.Path("app/ui/views/agent.py").read_text(encoding="utf-8")
    assert "stt.stream(" in source
    assert "aio.run(stt.transcribe(" not in source

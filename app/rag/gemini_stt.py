"""
Speech to text with Gemini's live transcription model.

This is the same path `scripts/live_console.py --mic` has always taken, lifted
out of that script so the Streamlit composer, the `/transcribe` route and the
terminal trace all share one implementation instead of three. The console
streamed from a microphone and the app posts a finished recording, but the wire
protocol is identical: open the Live websocket, push 16 kHz mono PCM at the
audio's own pace, and read `input_transcription` segments back.

Four details are not obvious and all of them were paid for once already:

1. **The Live API only accepts 16 kHz mono 16-bit PCM.** Anything else closes
   the socket with 1008 ("the operation was aborted") rather than saying what
   was wrong. Decoding is delegated to ffmpeg rather than done in Python — a
   hand-rolled `wave` + linear-interpolation resampler produced audio the API
   rejected, and the browser sends webm/ogg, which `wave` cannot open at all.

2. **The audio is paced, not dumped.** This is a realtime API; a whole file
   delivered in one burst is not the shape of traffic it expects, so chunks go
   out every `CHUNK_MS` of audio time.

3. **The socket often closes with 1008 *after* the final transcript arrives** —
   the close races the teardown. Treating that as a failure threw away good
   transcripts and silently fell back to the offline model, which is how a
   correct Persian sentence came back garbled. Anything already transcribed is
   the answer; only an empty result is a real failure.

4. **A custom vocabulary is what makes Persian legal terms survive.** «کلاسه»,
   «تجدیدنظرخواهی» and «بازیافت خسارت» come back as homophones without it, so
   the terms in `STT_VOCAB_FILE` are sent with every request.

`stream()` is the streaming form — it yields interim text as the model hears it
and the final segments as they settle. `transcribe()` is the one-shot form used
by callers that just want the finished string.
"""

from __future__ import annotations

import asyncio
import logging
import os
import pathlib
import subprocess

log = logging.getLogger(__name__)

# The Live API's required input format.
RATE = 16000
CHUNK_MS = 100
CHUNK_BYTES = RATE * 2 * CHUNK_MS // 1000

DEFAULT_MODEL = "gemini-3.5-transcribe-live"
_VOCAB_FILE = os.environ.get("STT_VOCAB_FILE", "data/stt_vocab_fa.txt")


def api_key() -> str | None:
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")


def model() -> str:
    return os.environ.get("GEMINI_STT_MODEL") or DEFAULT_MODEL


def available() -> bool:
    if not api_key():
        return False
    try:
        import google.genai  # noqa: F401
    except ModuleNotFoundError:
        return False
    return True


def vocabulary() -> list[str]:
    """The legal terms worth biasing the model toward, one per line."""
    path = pathlib.Path(_VOCAB_FILE)
    if not path.is_absolute():
        path = pathlib.Path(__file__).resolve().parents[2] / path
    try:
        return [line.strip() for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.startswith("#")]
    except OSError:
        return []


def to_pcm16(audio: bytes) -> bytes:
    """Any container the browser can record → 16 kHz mono PCM, via ffmpeg."""
    proc = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", "pipe:0",
         "-f", "s16le", "-ac", "1", "-ar", str(RATE), "pipe:1"],
        input=audio, capture_output=True,
    )
    if not proc.stdout:
        detail = proc.stderr.decode(errors="ignore")[:200]
        raise RuntimeError(f"صدا رمزگشایی نشد (ffmpeg): {detail}")
    return proc.stdout


def _config():
    from google.genai import types

    language = os.environ.get("STT_LANGUAGE", "fa-IR")
    settings = {
        "language_codes": [] if language in ("auto", "") else language.split(","),
        "mode": os.environ.get("STT_MODE", "SMART"),
    }
    if terms := vocabulary():
        settings["custom_vocabulary"] = terms
    return types.LiveConnectConfig(
        response_modalities=["TEXT"],
        input_audio_transcription=types.AudioTranscriptionConfig(**settings),
    )


def budget_for(frames: bytes) -> float:
    """How long to wait on the socket for a given amount of audio.

    The stream is paced at the audio's own rate, so a recording of N seconds
    takes at least N seconds to send; the rest is the model's thinking time and
    the close handshake.
    """
    seconds = len(frames) / (RATE * 2)
    return seconds + 25.0


async def stream(frames: bytes, *, timeout_s: float | None = None):
    """Transcribe PCM frames, yielding as the model hears them.

    Yields `{"type": "interim", "text": ...}` while a phrase is still settling
    and `{"type": "final", "text": ...}` once it has, then one
    `{"type": "done", "text": <everything joined>, "model": ...}`.

    The whole exchange is bounded. `session.receive()` does not always end on
    its own — the model may simply stop sending without ever setting
    `turn_complete`, and an unbounded `async for` over it then waits forever,
    which in the UI is a spinner that never stops. On timeout whatever has been
    transcribed so far is the result, for the same reason a 1008 close is not
    treated as failure.
    """
    from google import genai
    from google.genai import types

    key = api_key()
    if not key:
        raise RuntimeError(
            "GEMINI_API_KEY تنظیم نشده است — رونویسی گفتار به آن نیاز دارد."
        )

    finals: list[str] = []
    client = genai.Client(api_key=key)
    name = model()
    try:
        async with client.aio.live.connect(model=name, config=_config()) as session:

            async def send() -> None:
                for at in range(0, len(frames), CHUNK_BYTES):
                    await session.send_realtime_input(
                        audio=types.Blob(data=frames[at:at + CHUNK_BYTES],
                                         mime_type=f"audio/pcm;rate={RATE}"))
                    await asyncio.sleep(CHUNK_MS / 1000)
                await session.send_realtime_input(audio_stream_end=True)

            pump = asyncio.create_task(send())
            deadline = asyncio.get_running_loop().time() + (
                timeout_s if timeout_s is not None else budget_for(frames))
            inbox: asyncio.Queue = asyncio.Queue()

            async def reader() -> None:
                # Draining in its own task is what makes the deadline
                # enforceable: `session.receive()` can block indefinitely, and
                # only a task can be abandoned mid-await.
                try:
                    async for response in session.receive():
                        await inbox.put(response)
                finally:
                    await inbox.put(None)

            drain = asyncio.create_task(reader())
            try:
                while True:
                    left = deadline - asyncio.get_running_loop().time()
                    if left <= 0:
                        log.info("Gemini Live: stopped waiting after %.0fs with %d segment(s)",
                                 budget_for(frames), len(finals))
                        break
                    try:
                        response = await asyncio.wait_for(inbox.get(), timeout=left)
                    except asyncio.TimeoutError:
                        break
                    if response is None:      # the stream ended on its own
                        break
                    content = response.server_content
                    if not content:
                        continue
                    interim = getattr(content, "interim_input_transcription", None)
                    if interim and interim.text:
                        yield {"type": "interim", "text": interim.text}
                    final = getattr(content, "input_transcription", None)
                    if final and final.text:
                        finals.append(final.text)
                        yield {"type": "final", "text": final.text}
                    if getattr(content, "turn_complete", False):
                        break
            finally:
                drain.cancel()
                pump.cancel()
    except Exception as error:  # noqa: BLE001 — see (3) in the module docstring
        if not finals:
            raise RuntimeError(
                f"رونویسی گفتار ناموفق بود: {type(error).__name__}: {str(error)[:200]}"
            ) from error
        log.info("Gemini Live closed with %s after transcribing; keeping the transcript",
                 type(error).__name__)

    yield {"type": "done", "text": " ".join(t.strip() for t in finals).strip(),
           "model": name}


async def transcribe(audio: bytes, *, timeout_s: float | None = None) -> dict:
    """One recording in, the finished transcript out."""
    frames = await asyncio.to_thread(to_pcm16, audio)
    result = {"text": "", "model": model()}
    async for event in stream(frames, timeout_s=timeout_s):
        if event["type"] == "done":
            result = {"text": event["text"], "model": event["model"]}
    return {**result, "language": os.environ.get("STT_LANGUAGE", "fa-IR"),
            "provider": "gemini"}

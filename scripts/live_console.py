#!/usr/bin/env python3
"""
Live console — the whole assistant as a terminal trace.

One utterance in (microphone, audio file, or typed), and every stage prints as
it happens: the transcript streaming in, the router's decision, each tool call
with its arguments and result, each workflow step with its timing, and the
human gates where the run stops to ask you for the fields that came back empty.

It drives the *real* pipeline — `app.rag.orchestrator.route`,
`app.rag.tools.run_with_tools`, `app.rag.workflow` — so what you see here is
what the Streamlit app does, minus the UI. Nothing is mocked.

    scripts/live.sh                      typed input (no extra deps)
    scripts/live.sh --mic                microphone, live transcription
    scripts/live.sh --file session.mp3
    scripts/live.sh --model "local::qwen2.5:3b" --mode steps

Speech uses Gemini Live; put GEMINI_API_KEY in .env. Everything else uses the
model backend from .env (or --model, a registry id like "openai::gpt-4o-mini").
"""

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

RATE = 16000
CHUNK_MS = 100
CHUNK_BYTES = RATE * 2 * CHUNK_MS // 1000


# --------------------------------------------------------------------------- #
# Terminal drawing — one vocabulary for the whole trace
# --------------------------------------------------------------------------- #
class C:
    dim = "\033[2m"; bold = "\033[1m"; off = "\033[0m"
    teal = "\033[38;5;29m"; gold = "\033[38;5;178m"; red = "\033[38;5;124m"
    blue = "\033[38;5;24m"; grey = "\033[38;5;244m"

    @classmethod
    def strip(cls):
        for k, v in list(vars(cls).items()):
            if isinstance(v, str) and v.startswith("\033"):
                setattr(cls, k, "")


W = 78
_t0 = time.monotonic()


def clock() -> str:
    return f"{time.monotonic() - _t0:6.1f}s"


def stage(num: str, title: str, note: str = "") -> None:
    """A numbered band — the same numbered-section idea the UI uses."""
    head = f"{C.teal}{C.bold}┏━ {num} {title}{C.off}"
    tail = f" {C.grey}{note}{C.off}" if note else ""
    print(f"\n{head}{tail}")


def line(text: str, mark: str = "│") -> None:
    print(f"{C.teal}{mark}{C.off} {text}")


def field(key: str, value, mark: str = "│") -> None:
    if value in (None, "", [], {}):
        value = f"{C.red}— خالی{C.off}"
    line(f"{C.grey}{key:<14}{C.off} {value}", mark)


def close(note: str = "") -> None:
    print(f"{C.teal}┗━{C.off} {C.grey}{note}{C.off}" if note else f"{C.teal}┗━{C.off}")


def ms(value) -> str:
    if value is None:
        return ""
    return f"{C.gold}{int(value)}ms{C.off}" if value < 1000 else f"{C.gold}{value / 1000:.1f}s{C.off}"


# --------------------------------------------------------------------------- #
# 1 — Voice in
# --------------------------------------------------------------------------- #
async def transcribe(args) -> str:
    """Stream audio to Gemini Live and return the joined final transcript."""
    from google import genai
    from google.genai import types

    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        sys.exit(
            "[error] GEMINI_API_KEY is not set — speech needs it.\n"
            f"        add it to {Path.cwd() / '.env'}:  GEMINI_API_KEY=your_key\n"
            "        (https://aistudio.google.com/apikey), or use typed input."
        )

    vocab = [v.strip() for v in args.vocab.split(",") if v.strip()]
    if args.vocab_file:
        vocab += [l.strip() for l in Path(args.vocab_file).read_text(encoding="utf-8").splitlines() if l.strip()]

    tcfg = {"language_codes": [] if args.lang == "auto" else args.lang.split(","), "mode": args.stt_mode}
    if vocab:
        tcfg["custom_vocabulary"] = vocab

    stage("۰۱", "صدا · live transcription",
          f"{args.stt_model} · {args.lang} · {args.stt_mode} · {len(vocab)} واژه")

    finals: list[str] = []
    client = genai.Client(api_key=key)
    config = types.LiveConnectConfig(
        response_modalities=["TEXT"],
        input_audio_transcription=types.AudioTranscriptionConfig(**tcfg),
    )
    t_open = time.perf_counter()
    async with client.aio.live.connect(model=args.stt_model, config=config) as session:
        line(f"{C.grey}session open{C.off} {ms((time.perf_counter() - t_open) * 1000)}")
        first_token: float | None = None

        async def send():
            src = _file_chunks(args.file, args.speed) if args.file else _mic_chunks()
            async for chunk in src:
                await session.send_realtime_input(
                    audio=types.Blob(data=chunk, mime_type=f"audio/pcm;rate={RATE}")
                )
            await session.send_realtime_input(audio_stream_end=True)

        async def recv():
            nonlocal first_token
            while True:
                got = False
                async for resp in session.receive():
                    got = True
                    sc = resp.server_content
                    if not sc:
                        continue
                    interim = getattr(sc, "interim_input_transcription", None)
                    if interim and interim.text:
                        if first_token is None:
                            first_token = time.perf_counter() - t_open
                        print(f"\r\033[K{C.teal}│{C.off} {C.dim}{interim.text}{C.off}", end="", flush=True)
                    final = getattr(sc, "input_transcription", None)
                    if final and final.text:
                        if first_token is None:
                            first_token = time.perf_counter() - t_open
                        print(f"\r\033[K{C.teal}│{C.off} {final.text}")
                        finals.append(final.text)
                if not got:
                    break

        task = asyncio.create_task(recv())
        try:
            await send()
            await asyncio.sleep(args.tail)
        finally:
            task.cancel()

    text = " ".join(finals).strip()
    close(f"{len(finals)} قطعه · اولین واژه {first_token:.1f}s" if first_token
          else f"{len(finals)} قطعه")
    return text


async def _file_chunks(path, speed):
    import subprocess

    proc = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", path, "-f", "s16le", "-ac", "1", "-ar", str(RATE), "-"],
        capture_output=True,
    )
    if not proc.stdout:
        sys.exit(f"[error] ffmpeg produced no audio: {proc.stderr.decode(errors='ignore')}")
    pcm = proc.stdout
    line(f"{C.grey}{len(pcm) / (RATE * 2):.1f}s of audio · {speed}x{C.off}")
    for i in range(0, len(pcm), CHUNK_BYTES):
        yield pcm[i:i + CHUNK_BYTES]
        await asyncio.sleep(CHUNK_MS / 1000 / speed)


async def _mic_chunks():
    try:
        import sounddevice as sd
    except OSError as e:
        sys.exit(f"[error] sounddevice cannot load portaudio ({e}).\n"
                 "        sudo apt install libportaudio2   (then retry --mic)")
    q: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()

    def cb(indata, frames, t, status):
        loop.call_soon_threadsafe(q.put_nowait, bytes(indata))

    with sd.RawInputStream(samplerate=RATE, channels=1, dtype="int16",
                           blocksize=CHUNK_BYTES // 2, callback=cb):
        line(f"{C.bold}صحبت کنید…{C.off} {C.grey}Ctrl+C وقتی تمام شد{C.off}")
        try:
            while not stop.is_set():
                yield await q.get()
        except (asyncio.CancelledError, KeyboardInterrupt):
            return


# --------------------------------------------------------------------------- #
# 2 — Tool calls, printed as they fire
# --------------------------------------------------------------------------- #
def traced_tools():
    """The real tool set, each handler wrapped so the call prints live.

    `run_with_tools` only hands back its log at the end; wrapping the handlers
    is what turns it into a running trace without forking the loop.
    """
    from app.rag import tools as T

    calls: list[dict] = []

    def wrap(tool):
        async def handler(session, llm, **kwargs):
            n = len(calls) + 1
            args = ", ".join(f"{k}={v!r}" for k, v in kwargs.items())
            print(f"{C.teal}│{C.off} {C.blue}▸ {n}. {tool.name}{C.off}({C.grey}{args}{C.off})",
                  flush=True)
            t = time.perf_counter()
            try:
                out = await tool.handler(session, llm, **kwargs)
            except Exception as e:  # noqa: BLE001 — the loop reports it to the model
                out = {"error": f"{type(e).__name__}: {e}"}
            took = (time.perf_counter() - t) * 1000
            print(f"{C.teal}│{C.off}   {C.grey}↳{C.off} "
                  f"{T._summarise(tool.name, kwargs, out)}  {ms(took)}")
            calls.append({"tool": tool.name, "args": kwargs, "ms": took})
            return out

        return T.Tool(tool.name, tool.description, tool.parameters, handler)

    return [wrap(t) for t in T.TOOLS], calls


# --------------------------------------------------------------------------- #
# 3 — Human gates
# --------------------------------------------------------------------------- #
def ask(prompt: str, default: str = "") -> str:
    shown = f" {C.grey}[{default}]{C.off}" if default else ""
    try:
        got = input(f"{C.gold}?{C.off} {prompt}{shown}: ").strip()
    except EOFError:
        return default
    return got or default


def show_draft(draft: dict) -> None:
    ent = draft.get("entities") or {}
    field("عنوان", draft.get("title"))
    field("خلاصه", (draft.get("summary") or "")[:200])
    field("شمارهٔ پرونده", ent.get("case_number"))
    field("دادگاه", ent.get("court"))
    field("موضوع", ent.get("topic"))
    parties = draft.get("parties") or []
    field("طرفین", "، ".join(
        f"{p.get('name', '')} ({p.get('role', '')})" for p in parties if isinstance(p, dict)
    ) or None)


def gate_patch(step_id: str, payload: dict, state: dict, auto: bool) -> dict:
    """Show what the step produced, collect the user's corrections."""
    patch: dict = {}

    if step_id in ("extract", "labels"):
        draft = payload.get("draft") or state.get("draft") or {}
        if draft:
            show_draft(draft)

    if step_id == "timeline":
        rows = payload.get("rows") or state.get("timeline") or []
        for r in rows:
            line(f"{C.grey}{r.get('date') or '—':<12}{C.off} {r.get('title', '')}")
        if not rows:
            line(f"{C.grey}— بدون رویداد{C.off}")

    if step_id == "similar":
        items = payload.get("items") or state.get("similar") or []
        for i, s in enumerate(items, 1):
            line(f"{i}. {s.get('title', '')} {C.grey}· {s.get('why', '')}{C.off}")
        if not items:
            line(f"{C.grey}— مورد مشابهی پیدا نشد{C.off}")

    if step_id == "labels":
        labels = payload.get("labels") or state.get("labels") or []
        field("برچسب‌ها", "، ".join(labels) or None)

    # The part that matters: only ask about what actually came back empty.
    missing = payload.get("missing") or []
    if missing and not auto:
        print(f"{C.red}│ {len(missing)} فیلد لازم خالی است — تکمیل کنید{C.off}")
        draft = dict(payload.get("draft") or state.get("draft") or {})
        entities = dict(draft.get("entities") or {})
        for path, fa in missing:
            value = ask(f"  {fa}")
            if not value:
                continue
            if path.startswith("entities."):
                entities[path.split(".", 1)[1]] = value
            else:
                draft[path] = value
        draft["entities"] = entities
        patch["draft"] = draft

    if auto:
        line(f"{C.grey}(--yes) تأیید خودکار{C.off}")
        return patch

    answer = ask("تأیید و ادامه؟ (Enter=بله / e=ویرایش عنوان / q=توقف)")
    if answer.lower() == "q":
        raise KeyboardInterrupt
    if answer.lower() == "e":
        draft = dict(patch.get("draft") or payload.get("draft") or state.get("draft") or {})
        draft["title"] = ask("  عنوان تازه", draft.get("title", ""))
        patch["draft"] = draft
    return patch


# --------------------------------------------------------------------------- #
# 4 — The run
# --------------------------------------------------------------------------- #
async def handle(text: str, *, llm, sessions, args) -> None:
    from app.rag import workflow
    from app.rag.orchestrator import _INTENT_FA, corpus_stats, route
    from app.rag.tools import run_with_tools

    stage("۰۲", "مسیریاب · router")
    line(f"{C.dim}«{text[:120]}»{C.off}")
    t = time.perf_counter()
    decision = await route(llm, text, forced=args.intent)
    took = (time.perf_counter() - t) * 1000
    intent = decision.intent
    field("تصمیم", f"{C.bold}{_INTENT_FA.get(intent, intent)}{C.off} ({intent})")
    field("اطمینان", f"{decision.confidence:.0%} · {decision.reason}")
    close(f"router {int(took)}ms")

    if intent == "unclear":
        stage("۰۳", "ابهام")
        line(decision.clarification or "منظورتان روشن نیست.")
        close()
        return

    # ---- query / analytics / chat: the tool-calling agent -------------------
    if intent != "archive":
        tools, calls = traced_tools()
        stage("۰۳", "عامل ابزارگرا · tool loop", f"{len(tools)} ابزار در دسترس")
        system = (
            "You are a Persian legal-archive assistant. Use the tools to look "
            "things up in the archive before answering. Answer in Persian, "
            "citing what you found. Be concise."
        )
        t = time.perf_counter()
        async with sessions() as s:
            if intent == "analytics" and not args.force_tools:
                stats = await corpus_stats(s)
                field("اسناد", stats["documents"])
                field("مدخل‌ها", stats["entries"])
                field("قطعه‌ها", stats["chunks"])
                result_text = "، ".join(t["name"] for t in stats["topics"][:6])
                field("موضوعات", result_text)
                close(f"{int((time.perf_counter() - t) * 1000)}ms · بدون مدل")
                return
            loop = await run_with_tools(
                llm, s, prompt=text, system=system, tools=tools,
                max_rounds=args.rounds, max_tokens=700,
            )
        close(f"{len(calls)} فراخوانی · {loop.rounds} دور · "
              f"{int((time.perf_counter() - t) * 1000)}ms · {loop.model}")

        stage("۰۴", "پاسخ")
        for para in (loop.text or "—").split("\n"):
            line(para)
        close()
        return

    # ---- archive: the six-step workflow with gates --------------------------
    stage("۰۳", "خط لولهٔ ثبت · workflow", f"mode={args.mode}")
    # A resumed run re-reports every step it already ran, so print by
    # (step, status) pairs rather than by position — otherwise the whole list
    # repeats after each gate.
    printed: set = set()
    async with sessions() as s:
        view = await workflow.start(
            s, raw_text=text, source=args.source, llm=llm, mode=args.mode,
            forced_intent=args.intent,
        )
        run_id = view["id"]

    while True:
        steps = view.get("steps", [])
        for st in steps:
            key = (st["step_id"], st["status"], st.get("detail"))
            if st["status"] == "running" or key in printed:
                continue
            printed.add(key)
            icon = {"done": "✓", "awaiting_input": "◆", "failed": "✕", "skipped": "·"}.get(
                st["status"], "·")
            colour = {"done": C.teal, "awaiting_input": C.gold, "failed": C.red}.get(
                st["status"], C.grey)
            line(f"{colour}{icon}{C.off} {C.bold}{st['label']}{C.off} "
                 f"{C.grey}{st.get('detail') or st.get('error') or ''}{C.off} "
                 f"{ms(st.get('ms'))}")
        awaiting = next((s for s in reversed(steps) if s["status"] == "awaiting_input"), None)
        if awaiting is None:
            break

        state = view.get("state") or {}
        stage("◆", f"دروازهٔ انسانی · {awaiting['label']}")
        patch = gate_patch(awaiting["step_id"], awaiting.get("payload") or {}, state, args.yes)
        close()
        async with sessions() as s:
            view = await workflow.advance(s, run_id, llm, user_patch=patch or {})
        print()

    status = view.get("status")
    if status == "committed":
        close(f"ثبت شد · entry {view.get('entry_id')} · run {run_id}")
    else:
        close(f"وضعیت: {status} · run {run_id}")
    total = sum(s.get("ms") or 0 for s in view.get("steps", []))
    print(f"{C.grey}  مجموع زمان مدل/پایگاه‌داده: {total / 1000:.1f}s · "
          f"کنسول ساخت: http://localhost:8000/runs/view{C.off}")


class StubProvider:
    """A deterministic stand-in for `--offline`.

    No network, no tokens: it returns a plausible extraction built from the
    text itself, so the gates, the timings and the trace can be rehearsed when
    every real backend is down (Groq geo-blocked, Ollama not up). It never
    calls a tool, so the tool loop just answers in one round.
    """

    model = "stub (offline)"

    def is_available(self) -> bool:
        return True

    async def generate(self, prompt, *, system="", json_mode=False, tools=None, **kw):
        from app.llm.base import LLMResponse

        await asyncio.sleep(0.05)
        text = prompt.split("Message:\n")[-1].strip()
        if json_mode and "intent" in (system or ""):
            payload = {"intent": "archive", "confidence": 0.9, "clarify": ""}
        elif json_mode:
            first = text.replace("\n", " ").strip()
            for label in ("Text:", "متن:"):
                if first.startswith(label):
                    first = first[len(label):].strip()
            payload = {
                "title": first[:60] or "بدون عنوان",
                "summary": first[:200],
                "kind": "session",
                "parties": [], "events": [], "tags": [],
                "entities": {"case_number": "", "court": "", "topic": ""},
            }
        else:
            return LLMResponse(text="(offline stub — پاسخ مدل غیرفعال است)",
                               model=self.model)
        return LLMResponse(text=json.dumps(payload, ensure_ascii=False), model=self.model)


# --------------------------------------------------------------------------- #
async def main(args) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.db.engine import create_schema, resolve_database_url
    from app.llm.factory import get_llm_provider
    from app.llm.registry import resolve

    if args.offline:
        # ROUTER_MODEL would otherwise pull the router back onto a real
        # backend and defeat the point of --offline.
        os.environ.pop("ROUTER_MODEL", None)

    stage("۰۰", "راه‌اندازی · boot")
    t = time.perf_counter()
    engine = create_async_engine(resolve_database_url())
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    await create_schema(engine)
    field("پایگاه‌داده", f"آماده {ms((time.perf_counter() - t) * 1000)}")

    llm = StubProvider() if args.offline else (
        resolve(args.model) if args.model else get_llm_provider())
    ok = llm.is_available()
    if asyncio.iscoroutine(ok):  # providers differ on whether this is async
        ok = await ok
    field("مدل", f"{llm.__class__.__name__} · {getattr(llm, 'model', '?')} "
                 f"{'' if ok else C.red + '(در دسترس نیست)' + C.off}")
    field("ورودی", "میکروفون" if args.mic else (args.file or "متن تایپی"))
    close()
    if not ok:
        print(f"{C.red}[warn] مدل پاسخ نمی‌دهد — .env را بررسی کنید (LLM_PROVIDER / کلید){C.off}")

    try:
        while True:
            if args.text:
                text = args.text
            elif args.mic or args.file:
                text = await transcribe(args)
            else:
                text = ask(f"\n{C.bold}بگویید یا بنویسید{C.off} (q=خروج)")
                if text.lower() in ("q", "quit", "exit"):
                    break
            if not text.strip():
                print(f"{C.grey}— چیزی دریافت نشد{C.off}")
                if args.once or args.file or args.text:
                    break
                continue

            try:
                await handle(text, llm=llm, sessions=sessions, args=args)
            except KeyboardInterrupt:
                print(f"\n{C.grey}[gate] رها شد — ادامه{C.off}")
            except Exception as error:  # noqa: BLE001 — a bad backend ends the
                # utterance, not the session; the next one can use another model
                print(f"\n{C.red}✕ {type(error).__name__}{C.off}: {error}")
            if args.once or args.file or args.text:
                break
            args.mic = args.mic  # keep looping on the same source
    except KeyboardInterrupt:
        print(f"\n{C.grey}[stopped]{C.off}")
    finally:
        await engine.dispose()


def parse_args():
    p = argparse.ArgumentParser(
        description="Live terminal sandbox for the archive assistant",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    src = p.add_mutually_exclusive_group()
    src.add_argument("--mic", action="store_true", help="microphone → Gemini live transcription")
    src.add_argument("--file", help="audio file → Gemini live transcription")
    src.add_argument("--text", help="skip speech, run this text straight through")

    p.add_argument("--model", help='registry id, e.g. "local::qwen2.5:3b" or "openai::gpt-4o-mini"')
    p.add_argument("--mode", default="steps", choices=["steps", "review", "auto"],
                   help="how often the workflow stops for you (default: steps = every gate)")
    p.add_argument("--intent", choices=["query", "archive", "analytics", "chat"],
                   help="force the route instead of asking the router")
    p.add_argument("--offline", action="store_true",
                   help="no backend: a deterministic stub stands in for the model, "
                        "so the gates and the trace can be rehearsed")
    p.add_argument("--yes", action="store_true", help="accept every gate without asking")
    p.add_argument("--once", action="store_true", help="handle one utterance and exit")
    p.add_argument("--rounds", type=int, default=3, help="max tool-loop rounds")
    p.add_argument("--force-tools", action="store_true",
                   help="route analytics through the tool loop instead of the direct query")
    p.add_argument("--source", default="live-console", help="source label stored on the entry")

    p.add_argument("--stt-model", default="gemini-3.5-transcribe-live")
    p.add_argument("--stt-mode", default="VERBATIM", choices=["VERBATIM", "SMART"])
    p.add_argument("--lang", default="fa-IR", help="BCP-47 list, or 'auto'")
    p.add_argument("--vocab", default="", help="comma-separated custom vocabulary")
    p.add_argument("--vocab-file", help="one vocabulary term per line")
    p.add_argument("--speed", type=float, default=1.0, help="file streaming speed")
    p.add_argument("--tail", type=float, default=4.0, help="seconds to wait for the last segment")
    p.add_argument("--no-color", action="store_true")
    return p.parse_args()


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    a = parse_args()
    if a.no_color or not sys.stdout.isatty():
        C.strip()
    try:
        asyncio.run(main(a))
    except KeyboardInterrupt:
        print("\n[stopped]")

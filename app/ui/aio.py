"""
Running this app's async core from Streamlit's synchronous script.

The whole engine — asyncpg, async SQLAlchemy, every LLM provider — is async.
Streamlit re-runs the script top to bottom on every widget interaction, from a
plain synchronous function.

The naive bridge, `asyncio.run(coro)`, creates a *new* event loop per call and
closes it afterwards. That breaks anything cached across re-runs: an
`AsyncEngine` built on the first run holds asyncpg connections bound to the loop
that created them, so the second interaction dies with `Future attached to a
different loop` / `Event loop is closed`. Creating the engine per call instead
would work but re-opens the pool on every click.

So: one long-lived event loop on a daemon thread, started once per process and
kept for the life of the app. `run()` submits a coroutine to it and blocks for
the result. Every cached resource is created on that loop and every call reaches
it on that same loop, which is the invariant asyncpg needs.

Module-level rather than `@st.cache_resource` on purpose — module state survives
Streamlit re-runs via `sys.modules`, and this way scripts and tests can import
the same bridge without a Streamlit context.
"""

import asyncio
import threading
from concurrent.futures import Future
from typing import Any, Coroutine, TypeVar

T = TypeVar("T")

_loop: asyncio.AbstractEventLoop | None = None
_lock = threading.Lock()


def loop() -> asyncio.AbstractEventLoop:
    """The process-wide background event loop, started on first use."""
    global _loop
    if _loop is not None and not _loop.is_closed():
        return _loop
    with _lock:
        if _loop is not None and not _loop.is_closed():
            return _loop
        new_loop = asyncio.new_event_loop()
        ready = threading.Event()

        def _runner() -> None:
            asyncio.set_event_loop(new_loop)
            new_loop.call_soon(ready.set)
            new_loop.run_forever()

        threading.Thread(target=_runner, name="rag-aio", daemon=True).start()
        ready.wait(timeout=10)
        _loop = new_loop
        return _loop


def iterate(agen, *, timeout: float | None = None):
    """Drive an async generator from synchronous code, yielding as it goes.

    Streamlit's `st.write_stream` wants an ordinary generator. Pumping the async
    one item at a time over the shared loop keeps every await on the same loop
    the engine was built on, which is the invariant asyncpg needs — and it means
    tokens reach the page as they arrive instead of after the whole answer.
    """
    try:
        while True:
            try:
                yield asyncio.run_coroutine_threadsafe(agen.__anext__(), loop()).result(timeout)
            except StopAsyncIteration:
                return
    finally:
        # Close it on the loop even if the consumer walked away early. An HTTP
        # stream left dangling inside an async generator is finalised by the
        # interpreter later, on the wrong loop, which surfaces as
        # "generator didn't stop after athrow()".
        try:
            asyncio.run_coroutine_threadsafe(agen.aclose(), loop()).result(5)
        except Exception:  # noqa: BLE001 — best-effort cleanup
            pass


def run(coro: Coroutine[Any, Any, T], *, timeout: float | None = None) -> T:
    """Run `coro` on the background loop and block until it returns.

    Exceptions propagate to the caller unchanged, so Streamlit code can wrap
    this in a normal try/except.
    """
    future: Future[T] = asyncio.run_coroutine_threadsafe(coro, loop())
    return future.result(timeout)

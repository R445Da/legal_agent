"""
Process-wide resources for the Streamlit app, built once and reused.

Streamlit re-runs the script on every interaction. Without caching, each click
would rebuild the database engine, re-open the connection pool and re-load the
ONNX embedding + reranker models — seconds of work per keystroke.

**Build everything from the script thread, never from inside a coroutine.**
`_build()` calls `aio.run()` to create the schema. If it were reached lazily
from a coroutine already executing on the background loop, that `aio.run()`
would submit work to the loop and then block the loop's own thread waiting for
it — a self-deadlock that hangs the request forever with no error. So `init()`
is called once per re-run from the script thread, and `session()` only ever
reads the session factory it left behind.
"""

from contextlib import asynccontextmanager

import streamlit as st
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.engine import create_schema, resolve_database_url
from app.ui import aio

# Set by init() on the script thread; read by session() on the loop thread.
_SESSIONS: async_sessionmaker | None = None


@st.cache_resource(show_spinner="در حال آماده‌سازی پایگاه‌داده…")
def _build(loop_id: int):
    """The async engine + session factory, with the schema ensured once.

    `resolve_database_url()` boots the project-local `pgserver` cluster on the
    first call when DATABASE_URL=embedded, which is why this is worth caching
    hard — it is the slowest single step in app startup.

    `loop_id` is not used in the body — it is the cache key. asyncpg binds every
    pooled connection to the event loop that created it, so an engine outlives
    its loop only as a trap. When Streamlit hot-reloads on save it re-imports
    `aio`, which starts a *new* loop while this cache survives; the next query
    then fails with "Future ... attached to a different loop". Keying the cache
    on the loop's identity means a new loop transparently builds a new engine.
    """
    engine = create_async_engine(resolve_database_url())
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    aio.run(create_schema(engine))  # safe: we are on the script thread
    return engine, sessions


def init() -> None:
    """Build (or fetch) the shared resources. Must run on the script thread."""
    global _SESSIONS
    _SESSIONS = _build(id(aio.loop()))[1]


@asynccontextmanager
async def session():
    """`async with session() as s:` — one short-lived session per operation,
    mirroring what the FastAPI routes do per request."""
    if _SESSIONS is None:
        raise RuntimeError(
            "app.ui.resources.init() must run on the script thread before any "
            "database work is submitted to the background loop."
        )
    async with _SESSIONS() as s:
        yield s


@st.cache_resource(show_spinner="در حال بارگذاری مدل تعبیه…")
def warm_embeddings() -> str:
    """Force the first (slow) fastembed download/load at a moment the UI can
    show a spinner for, instead of inside the user's first query."""
    from app.config import settings
    from app.rag.embeddings import embed_query

    aio.run(embed_query("سلام"))
    return settings.embedding_model


@st.cache_resource(show_spinner="در حال بارگذاری بازرتبه‌بند…")
def warm_reranker(model_name: str) -> str:
    """Load the cross-encoder once. Keyed on the model name so switching
    rerankers in the sidebar loads the new one and keeps both cached."""
    from app.rag.rerank import load_model

    load_model(model_name)
    return model_name

"""
Test fixtures.

Unit tests never touch the network or the database: they drive the tool loop
and the provider request builders with `FakeProvider`, which returns scripted
`LLMResponse`s and records every call. Tests marked `db` open the database
named by DATABASE_URL (or the embedded cluster in `PG_DATA_DIR`, defaulting to
a throw-away `.pgdata-test`) and seed it with the mock insurance archive once.

The environment is pinned before any `app.*` import so `.env` cannot pull a
real provider or a downloaded embedding model into a test run.
"""

import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_ENV = {
    "LLM_PROVIDER": "mock", "LLM_MODEL": "rules-v1", "ROUTER_MODEL": "mock::rules-v1",
    "EMBEDDING_MODEL": "hash://384", "EMBEDDING_DIM": "384", "EMBEDDING_PREFIXES": "0",
    "RERANK": "0", "HYBRID": "1", "TS_CONFIG": "simple", "STT": "0",
    "TOOL_LOOP": "native", "PROMPT_CACHE": "1", "SIMILAR_TOOL_BUDGET_S": "0", "LABELS_LLM": "0",
    "PG_DATA_DIR": ".pgdata-test", "API_TOKEN": "",
}
for _key, _value in _ENV.items():
    os.environ.setdefault(_key, _value)

import pytest  # noqa: E402

from app.llm.base import LLMProvider, LLMResponse  # noqa: E402


def resp(text: str = "", tool_calls: list[dict] | None = None, turn=None, **fields) -> LLMResponse:
    """A scripted model reply."""
    return LLMResponse(
        text=text, model=fields.pop("model", "fake-1"), tool_calls=tool_calls,
        stop_reason="tool_use" if tool_calls else "end_turn",
        input_tokens=fields.pop("input_tokens", 100), output_tokens=fields.pop("output_tokens", 20),
        latency_ms=fields.pop("latency_ms", 5.0), turn=turn, **fields,
    )


class FakeProvider(LLMProvider):
    """Replays scripted responses; the last one repeats. Records every call."""

    name = "fake"
    supports_native_tools = True
    supports_json_schema = True
    supports_prompt_cache = True

    def __init__(self, responses: list[LLMResponse]):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def is_available(self) -> bool:
        return True

    def _next(self) -> LLMResponse:
        return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]

    async def generate(self, prompt: str, **kwargs) -> LLMResponse:
        self.calls.append({"method": "generate", "prompt": prompt, **kwargs})
        return self._next()

    async def chat(self, messages: list[dict], **kwargs) -> LLMResponse:
        self.calls.append({"method": "chat", "messages": [dict(m) for m in messages], **kwargs})
        return self._next()


class FakeTextProvider(LLMProvider):
    """A provider without native tool turns: only `generate()`; `chat()` is the
    base-class fallback that flattens the transcript."""

    name = "faketext"

    def __init__(self, responses: list[LLMResponse]):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def is_available(self) -> bool:
        return True

    async def generate(self, prompt: str, **kwargs) -> LLMResponse:
        self.calls.append({"method": "generate", "prompt": prompt, **kwargs})
        return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]


# --------------------------------------------------------------------------- #
# Database (tests marked `db`)
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="session")
async def db_engine():
    from sqlalchemy import func, select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.db.engine import create_schema, resolve_database_url
    from app.db.models import LegalCase

    engine = create_async_engine(resolve_database_url())
    await create_schema(engine)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as session:
        n = await session.scalar(select(func.count()).select_from(LegalCase))
    if not n:
        import argparse

        from scripts import seed_mock

        await seed_mock.main(argparse.Namespace(n=40, seed=7, reset=True))
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(db_engine):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    sessions = async_sessionmaker(db_engine, expire_on_commit=False)
    async with sessions() as session:
        yield session

"""
Persistence and live events for pipeline runs (`app/rag/workflow.py`).

A `Run` is the durable checkpoint of one entry-building pass; its `RunStep` rows
are the log. This module is the only place that touches those two tables, so the
Streamlit UI and the FastAPI build console read a run the same way.

The Streamlit app and the API server are **separate processes** on one embedded
Postgres, so the in-process pub/sub here only carries runs the *same* process
drives. The console's SSE endpoint polls `RunStep` for everything else — which is
the normal case, because runs are started from Streamlit.
"""

import asyncio
from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Run, RunStep

# --------------------------------------------------------------------------- #
# Live events — best-effort, single process
# --------------------------------------------------------------------------- #
_subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)


def subscribe(run_id: str) -> asyncio.Queue:
    """A queue that receives this run's step events. Call from an async context
    so it binds to the running loop; remember to `unsubscribe`."""
    queue: asyncio.Queue = asyncio.Queue()
    _subscribers[str(run_id)].add(queue)
    return queue


def unsubscribe(run_id: str, queue: asyncio.Queue) -> None:
    _subscribers.get(str(run_id), set()).discard(queue)
    if not _subscribers.get(str(run_id)):
        _subscribers.pop(str(run_id), None)


def publish(run_id: str, event: dict) -> None:
    for queue in list(_subscribers.get(str(run_id), ())):
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:  # unbounded by default; guard anyway
            pass


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #
async def create_run(
    session: AsyncSession, *, raw_text: str, source: str | None = None,
    kind: str = "archive", state: dict | None = None,
) -> Run:
    run = Run(
        kind=kind, status="running", raw_text=raw_text,
        source=source, state=state or {},
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return run


async def get_run(session: AsyncSession, run_id) -> Run | None:
    return await session.get(Run, run_id)


async def load_run(session: AsyncSession, run_id) -> dict | None:
    """Run + ordered steps as plain dicts — what the console and the UI render."""
    run = await session.get(Run, run_id)
    if run is None:
        return None
    steps = (await session.execute(
        select(RunStep).where(RunStep.run_id == run.id).order_by(RunStep.seq)
    )).scalars().all()
    return _run_view(run, steps)


async def list_runs(session: AsyncSession, *, limit: int = 50) -> list[dict]:
    rows = (await session.execute(
        select(Run).order_by(Run.created_at.desc()).limit(limit)
    )).scalars().all()
    counts = dict((await session.execute(
        select(RunStep.run_id, func.count()).group_by(RunStep.run_id)
    )).all())
    return [
        {
            "id": str(r.id), "kind": r.kind, "status": r.status, "source": r.source,
            "entry_id": str(r.entry_id) if r.entry_id else None,
            "step_count": counts.get(r.id, 0),
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in rows
    ]


async def save_state(
    session: AsyncSession, run_id, state: dict, *, status: str | None = None,
) -> None:
    run = await session.get(Run, run_id)
    if run is None:
        return
    run.state = state
    if status:
        run.status = status
    queued = await _emit(session, "run.status", {"run_id": str(run_id), "status": run.status,
                                                 "source": run.source, "entry_id": str(run.entry_id) if run.entry_id else None}) if status else 0
    await session.commit()
    publish(run_id, {"type": "state", "status": run.status})
    if queued:
        _drain_soon(session)


async def set_status(
    session: AsyncSession, run_id, status: str, *, entry_id=None,
) -> None:
    run = await session.get(Run, run_id)
    if run is None:
        return
    run.status = status
    if entry_id:
        run.entry_id = entry_id
    queued = await _emit(session, "run.status", {"run_id": str(run_id), "status": status,
                                                 "source": run.source, "entry_id": str(entry_id) if entry_id else None})
    await session.commit()
    publish(run_id, {"type": "status", "status": status})
    if queued:
        _drain_soon(session)


async def record_step(
    session: AsyncSession, run_id, *, seq: int, step_id: str, label: str,
    status: str, detail: str | None = None, payload: dict | None = None,
    error: str | None = None, ms: int | None = None,
) -> RunStep:
    """Upsert the step row at (run_id, seq).

    One row per step position: a retry overwrites it, so the log shows the latest
    attempt rather than a pile of failures.
    """
    step = await session.scalar(
        select(RunStep).where(RunStep.run_id == run_id, RunStep.seq == seq)
    )
    if step is None:
        step = RunStep(run_id=run_id, seq=seq, step_id=step_id, label=label)
        session.add(step)
    step.step_id = step_id
    step.label = label
    step.status = status
    # Keep the prior value when the caller passes None — approving a gate updates
    # the detail but must not wipe the timing the step's own run recorded.
    if detail is not None:
        step.detail = detail
    if payload is not None:
        step.payload = payload
    step.error = error
    if ms is not None:
        step.ms = ms
    event = {
        "type": "step", "seq": seq, "step_id": step_id, "label": label,
        "status": status, "detail": detail, "ms": ms, "error": error,
    }
    queued = await _emit(session, "run.step", {"run_id": str(run_id), **{k: v for k, v in event.items() if k != "type"}})
    await session.commit()
    await session.refresh(step)
    publish(run_id, event)
    if queued:
        _drain_soon(session)
    return step


# --------------------------------------------------------------------------- #
# Outbound webhooks — queued in the same transaction as the row they report
# --------------------------------------------------------------------------- #
async def _emit(session: AsyncSession, event: str, data: dict) -> int:
    from app.rag import hooks

    try:
        return await hooks.emit(session, event, data)
    except Exception:  # noqa: BLE001 — a missing table on an old DB must not break a run
        return 0


def _drain_soon(session: AsyncSession) -> None:
    from app.rag import hooks

    hooks.drain_soon(session)


def _run_view(run: Run, steps: list[RunStep]) -> dict:
    return {
        "id": str(run.id), "kind": run.kind, "status": run.status,
        "raw_text": run.raw_text, "source": run.source, "state": run.state or {},
        "entry_id": str(run.entry_id) if run.entry_id else None,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
        "steps": [
            {
                "seq": s.seq, "step_id": s.step_id, "label": s.label,
                "status": s.status, "detail": s.detail, "payload": s.payload or {},
                "error": s.error, "ms": s.ms,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in steps
        ],
    }

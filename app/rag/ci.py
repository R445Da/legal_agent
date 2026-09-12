"""
CI events, as received — and the per-run picture built from them.

Three sources land in `ci_events`:

- GitHub's own webhooks (`workflow_run`, `workflow_job`) via POST /hooks/github,
  verified against GITHUB_WEBHOOK_SECRET;
- stage reports from `scripts/ci_status.sh` inside the workflow via
  POST /ci/status (a no-op when CI_STATUS_URL is not configured);
- `scripts/replay_ci.py`, which replays recorded or synthesised runs so the
  dashboard can show a live pipeline with no network and no GitHub auth.

`list_ci_runs()` folds the events into runs → jobs → stages, newest first.
"""

import datetime as dt

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CiEvent

JOBS = ("test", "build", "smoke")


def _ts(value) -> dt.datetime | None:
    if not value:
        return None
    if isinstance(value, dt.datetime):
        return value
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


async def _insert(session: AsyncSession, values: dict) -> bool:
    # Stamp arrival here, not with the database's `now()`: every row written
    # in one transaction would share the transaction timestamp, and a replayed
    # burst would then fold out of order.
    values.setdefault("received_at", dt.datetime.now(dt.timezone.utc))
    stmt = insert(CiEvent).values(**values).on_conflict_do_nothing(index_elements=["delivery_id"])
    result = await session.execute(stmt)
    return bool(result.rowcount)


async def record_github(session: AsyncSession, *, delivery_id: str, event: str, payload: dict,
                        source: str = "github") -> bool:
    """Store one GitHub webhook. Returns False when this delivery was seen before."""
    repo = (payload.get("repository") or {}).get("full_name")
    values: dict = {"delivery_id": delivery_id, "source": source, "event": event,
                    "action": payload.get("action"), "repo": repo, "payload": payload}
    if event == "workflow_run" and isinstance(payload.get("workflow_run"), dict):
        run = payload["workflow_run"]
        values.update({
            "workflow_name": run.get("name"), "run_id": str(run.get("id")), "run_number": run.get("run_number"),
            "head_sha": run.get("head_sha"), "head_branch": run.get("head_branch"),
            "status": run.get("status"), "conclusion": run.get("conclusion"), "html_url": run.get("html_url"),
            "started_at": _ts(run.get("run_started_at")),
            "completed_at": _ts(run.get("updated_at")) if run.get("status") == "completed" else None,
        })
    elif event == "workflow_job" and isinstance(payload.get("workflow_job"), dict):
        job = payload["workflow_job"]
        values.update({
            "workflow_name": job.get("workflow_name"), "job_name": job.get("name"),
            "run_id": str(job.get("run_id")), "run_number": job.get("run_attempt") and None,
            "head_sha": job.get("head_sha"), "head_branch": job.get("head_branch"),
            "status": job.get("status"), "conclusion": job.get("conclusion"), "html_url": job.get("html_url"),
            "started_at": _ts(job.get("started_at")), "completed_at": _ts(job.get("completed_at")),
        })
    return await _insert(session, values)


async def record_status(session: AsyncSession, body: dict, *, source: str = "ci-step") -> bool:
    """Store one stage report from the workflow (`scripts/ci_status.sh`)."""
    ts = body.get("ts") or dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    run_id = str(body.get("run_id") or "local")
    delivery_id = body.get("delivery_id") or f"ci:{run_id}:{body.get('job')}:{body.get('stage')}:{body.get('status')}:{ts}"
    values = {
        "delivery_id": delivery_id, "source": source, "event": "ci_status", "action": body.get("status"),
        "repo": body.get("repo"), "workflow_name": body.get("workflow") or "docker",
        "job_name": body.get("job"), "stage": body.get("stage"), "run_id": run_id,
        "run_number": int(body["run_number"]) if str(body.get("run_number") or "").isdigit() else None,
        "head_sha": body.get("sha"), "head_branch": body.get("branch"),
        "status": body.get("status"), "conclusion": body.get("conclusion") or None,
        "html_url": body.get("url"), "started_at": _ts(ts) if body.get("status") == "in_progress" else None,
        "completed_at": _ts(ts) if body.get("status") == "completed" else None,
        "payload": body,
    }
    return await _insert(session, values)


async def list_ci_runs(session: AsyncSession, *, limit: int = 10, max_events: int = 600) -> list[dict]:
    """Runs → jobs → stages, newest run first, from the latest events."""
    rows = (await session.execute(
        select(CiEvent).order_by(CiEvent.received_at.desc()).limit(max_events)
    )).scalars().all()
    runs: dict[str, dict] = {}
    for ev in reversed(rows):  # chronological
        key = ev.run_id or "local"
        run = runs.setdefault(key, {
            "run_id": key, "run_number": None, "workflow": None, "branch": None, "sha": None, "html_url": None,
            "status": None, "conclusion": None, "started_at": None, "updated_at": None, "jobs": {}, "events": 0,
            "source": ev.source,
        })
        run["events"] += 1
        run["updated_at"] = (ev.received_at or run["updated_at"])
        for field, value in (("run_number", ev.run_number), ("workflow", ev.workflow_name), ("branch", ev.head_branch),
                             ("sha", ev.head_sha), ("html_url", ev.html_url)):
            if value and not run.get(field) or (field == "html_url" and value and ev.event == "workflow_run"):
                run[field] = value
        if ev.event == "workflow_run":
            run["status"], run["conclusion"] = ev.status, ev.conclusion
            run["started_at"] = run["started_at"] or ev.started_at
        elif ev.event in ("workflow_job", "ci_status") and ev.job_name:
            job = run["jobs"].setdefault(ev.job_name, {"name": ev.job_name, "status": None, "conclusion": None,
                                                       "stages": [], "started_at": None, "completed_at": None})
            if ev.event == "workflow_job":
                job["status"], job["conclusion"] = ev.status, ev.conclusion
                job["started_at"] = job["started_at"] or ev.started_at
                job["completed_at"] = ev.completed_at or job["completed_at"]
                for step in (ev.payload.get("workflow_job") or {}).get("steps") or []:
                    _upsert_stage(job, step.get("name"), step.get("status"), step.get("conclusion"),
                                  step.get("completed_at") or step.get("started_at"))
            else:
                stage = ev.stage or "—"
                if stage in ("start", "finish"):
                    job["status"] = ev.status
                    job["conclusion"] = ev.conclusion or job["conclusion"]
                    if stage == "start":
                        job["started_at"] = job["started_at"] or ev.received_at
                    else:
                        job["completed_at"] = ev.received_at
                else:
                    _upsert_stage(job, stage, ev.status, ev.conclusion, ev.received_at)
                    if job["status"] not in ("completed",):
                        job["status"] = "in_progress"
            if not run["started_at"]:
                run["started_at"] = job["started_at"] or ev.received_at
    out = []
    for run in runs.values():
        jobs = list(run["jobs"].values())
        if run["status"] is None and jobs:
            if all(j["status"] == "completed" for j in jobs) and {j["name"] for j in jobs} >= set(JOBS[:1]):
                run["status"] = "completed"
                run["conclusion"] = "failure" if any(j["conclusion"] == "failure" for j in jobs) else (
                    "success" if all(j["conclusion"] == "success" for j in jobs) else None)
            else:
                run["status"] = "in_progress"
        jobs.sort(key=lambda j: JOBS.index(j["name"]) if j["name"] in JOBS else 99)
        out.append({**run, "jobs": jobs,
                    "started_at": run["started_at"].isoformat() if run["started_at"] else None,
                    "updated_at": run["updated_at"].isoformat() if run["updated_at"] else None})
    out.sort(key=lambda r: r["updated_at"] or "", reverse=True)
    return out[:limit]


def _upsert_stage(job: dict, name: str | None, status: str | None, conclusion: str | None, ts) -> None:
    if not name:
        return
    when = ts.isoformat() if isinstance(ts, dt.datetime) else (str(ts) if ts else None)
    for stage in job["stages"]:
        if stage["name"] == name:
            stage.update({"status": status, "conclusion": conclusion, "ts": when})
            return
    job["stages"].append({"name": name, "status": status, "conclusion": conclusion, "ts": when})

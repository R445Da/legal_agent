"""
Replay CI events into the app so the dashboard shows a live pipeline —
offline, without GitHub webhooks reaching this machine, without any auth.

    python -m scripts.replay_ci                                   # all fixtures, via /ci/status-style posts
    python -m scripts.replay_ci --fixture data/ci/fixtures/run-4-v2.json --delay 1.5
    python -m scripts.replay_ci --synthesize --run-number 9 --branch v3 --fail-at build
    python -m scripts.replay_ci --via github --secret "$GITHUB_WEBHOOK_SECRET"   # exercise the signed receiver
    python -m scripts.replay_ci --direct                          # write ci_events rows straight into the database

Fixtures come from `scripts/capture_ci.py` (real runs) or `--synthesize` (a
made-up run in GitHub's shape). `--via status` (default) posts each event's
job/stage state to POST /ci/status with the API token; `--via github` signs
the original payloads for POST /hooks/github.
"""

import argparse
import datetime as dt
import json
import os
import pathlib
import sys
import time
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

JOBS = ("test", "build", "smoke")
STAGES = {
    "test": ["Lint (ruff)", "Unit tests (no database)", "Insurance edition seeds", "Database tests",
             "Every API endpoint answers", "Every UI section renders", "The packaged archive restores"],
    "build": ["Set up QEMU", "Log in to GHCR", "Build and push"],
    "smoke": ["Image refuses a missing DATABASE_URL"],
}


def synthesize(run_number: int, branch: str, sha: str, *, fail_at: str | None = None,
               repo: str = "R445Da/legal_agent") -> list[dict]:
    """A whole run in GitHub's webhook shape: run requested → jobs → completed."""
    run_id = 90_000_000_000 + run_number
    t0 = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=12)
    stamp = lambda m: (t0 + dt.timedelta(minutes=m)).isoformat(timespec="seconds").replace("+00:00", "Z")  # noqa: E731
    base_run = {"id": run_id, "name": "docker", "run_number": run_number, "head_sha": sha, "head_branch": branch,
                "event": "push", "html_url": f"https://github.com/{repo}/actions/runs/{run_id}",
                "run_started_at": stamp(0), "path": ".github/workflows/docker.yml"}
    events = [{"kind": "workflow_run", "delivery_id": f"syn:{run_id}:run:requested",
               "payload": {"action": "requested", "repository": {"full_name": repo},
                           "workflow_run": {**base_run, "status": "queued", "conclusion": None, "updated_at": stamp(0)}}},
              {"kind": "workflow_run", "delivery_id": f"syn:{run_id}:run:in_progress",
               "payload": {"action": "in_progress", "repository": {"full_name": repo},
                           "workflow_run": {**base_run, "status": "in_progress", "conclusion": None, "updated_at": stamp(0)}}}]
    minute = 0
    failed = False
    for j, job_name in enumerate(JOBS):
        if failed:
            break
        job_id = run_id * 10 + j
        steps = [{"name": s, "number": i + 1} for i, s in enumerate(STAGES[job_name])]
        base_job = {"id": job_id, "run_id": run_id, "name": job_name, "workflow_name": "docker", "head_sha": sha,
                    "head_branch": branch, "html_url": f"https://github.com/{repo}/actions/runs/{run_id}/job/{job_id}",
                    "run_attempt": 1}
        events.append({"kind": "workflow_job", "delivery_id": f"syn:{run_id}:job:{job_id}:queued",
                       "payload": {"action": "queued", "repository": {"full_name": repo},
                                   "workflow_job": {**base_job, "status": "queued", "conclusion": None, "started_at": None,
                                                    "completed_at": None,
                                                    "steps": [{**s, "status": "queued", "conclusion": None} for s in steps]}}})
        started = stamp(minute)
        for i in range(len(steps)):
            done = [{**s, "status": "completed", "conclusion": "success", "started_at": stamp(minute), "completed_at": stamp(minute + 1)}
                    for s in steps[:i]]
            current = [{**steps[i], "status": "in_progress", "conclusion": None, "started_at": stamp(minute + i)}]
            rest = [{**s, "status": "queued", "conclusion": None} for s in steps[i + 1:]]
            events.append({"kind": "workflow_job", "delivery_id": f"syn:{run_id}:job:{job_id}:in_progress:{i}",
                           "payload": {"action": "in_progress", "repository": {"full_name": repo},
                                       "workflow_job": {**base_job, "status": "in_progress", "conclusion": None,
                                                        "started_at": started, "completed_at": None,
                                                        "steps": done + current + rest}}})
        minute += len(steps)
        conclusion = "failure" if fail_at == job_name else "success"
        events.append({"kind": "workflow_job", "delivery_id": f"syn:{run_id}:job:{job_id}:completed",
                       "payload": {"action": "completed", "repository": {"full_name": repo},
                                   "workflow_job": {**base_job, "status": "completed", "conclusion": conclusion,
                                                    "started_at": started, "completed_at": stamp(minute),
                                                    "steps": [{**s, "status": "completed",
                                                               "conclusion": conclusion if k == len(steps) - 1 else "success",
                                                               "started_at": stamp(minute), "completed_at": stamp(minute)}
                                                              for k, s in enumerate(steps)]}}})
        failed = conclusion == "failure"
    events.append({"kind": "workflow_run", "delivery_id": f"syn:{run_id}:run:completed",
                   "payload": {"action": "completed", "repository": {"full_name": repo},
                               "workflow_run": {**base_run, "status": "completed",
                                                "conclusion": "failure" if failed else "success",
                                                "updated_at": stamp(minute)}}})
    return events


def load_fixtures(paths: list[str]) -> list[list[dict]]:
    out = []
    for p in paths:
        out.append(json.loads(pathlib.Path(p).read_text(encoding="utf-8")))
    return out


def _post(url: str, body: bytes, headers: dict) -> tuple[int, str]:
    req = urllib.request.Request(url, data=body, method="POST", headers={"content-type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")[:200]
    except urllib.error.HTTPError as error:  # type: ignore[attr-defined]
        return error.code, error.read().decode("utf-8", "replace")[:200]


def status_bodies(event: dict) -> list[dict]:
    """The /ci/status reports equivalent to one GitHub event (job + stages)."""
    kind, payload = event["kind"], event["payload"]
    common = {"repo": (payload.get("repository") or {}).get("full_name"), "source": "replay"}
    if kind == "workflow_run":
        run = payload["workflow_run"]
        return [{**common, "run_id": run["id"], "run_number": run.get("run_number"), "workflow": run.get("name"),
                 "job": None, "stage": None, "status": run.get("status"), "conclusion": run.get("conclusion"),
                 "sha": run.get("head_sha"), "branch": run.get("head_branch"), "url": run.get("html_url"),
                 "ts": run.get("updated_at") or run.get("run_started_at"), "delivery_id": "st:" + event["delivery_id"],
                 "kind": "workflow_run"}]
    job = payload["workflow_job"]
    base = {**common, "run_id": job["run_id"], "workflow": job.get("workflow_name"), "job": job.get("name"),
            "sha": job.get("head_sha"), "branch": job.get("head_branch"), "url": job.get("html_url")}
    out = [{**base, "stage": "start" if job.get("status") != "completed" else "finish", "status": job.get("status"),
            "conclusion": job.get("conclusion"), "ts": job.get("completed_at") or job.get("started_at"),
            "delivery_id": "st:" + event["delivery_id"]}]
    for i, step in enumerate(job.get("steps") or []):
        if step.get("status") in ("in_progress", "completed"):
            out.append({**base, "stage": step.get("name"), "status": step.get("status"), "conclusion": step.get("conclusion"),
                        "ts": step.get("completed_at") or step.get("started_at"),
                        "delivery_id": f"st:{event['delivery_id']}:step{i}:{step.get('status')}"})
    return out


async def write_direct(runs: list[list[dict]]) -> int:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.db.engine import create_schema, resolve_database_url
    from app.rag import ci

    engine = create_async_engine(resolve_database_url())
    await create_schema(engine)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    n = 0
    async with sessions() as session:
        for events in runs:
            for event in events:
                if await ci.record_github(session, delivery_id=event["delivery_id"], event=event["kind"],
                                          payload=event["payload"], source="replay"):
                    n += 1
        await session.commit()
    await engine.dispose()
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture", action="append", help="fixture file(s); default: every file in data/ci/fixtures")
    ap.add_argument("--synthesize", action="store_true", help="make up a run instead of using fixtures")
    ap.add_argument("--run-number", type=int, default=7)
    ap.add_argument("--branch", default="v3")
    ap.add_argument("--sha", default="3a7e3edc1234567890abcdef1234567890abcdef")
    ap.add_argument("--fail-at", choices=JOBS, default=None)
    ap.add_argument("--write", help="with --synthesize: also save the run as a fixture file")
    ap.add_argument("--base", default=os.environ.get("BASE", "http://127.0.0.1:8000"))
    ap.add_argument("--token", default=os.environ.get("API_TOKEN", ""))
    ap.add_argument("--via", choices=("status", "github"), default="status")
    ap.add_argument("--secret", default=os.environ.get("GITHUB_WEBHOOK_SECRET", ""), help="for --via github")
    ap.add_argument("--delay", type=float, default=0.0, help="seconds between events, to watch it animate")
    ap.add_argument("--direct", action="store_true", help="write ci_events rows directly (no API needed)")
    args = ap.parse_args()

    if args.synthesize:
        runs = [synthesize(args.run_number, args.branch, args.sha, fail_at=args.fail_at)]
        if args.write:
            pathlib.Path(args.write).parent.mkdir(parents=True, exist_ok=True)
            pathlib.Path(args.write).write_text(json.dumps(runs[0], ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"wrote {args.write}")
    else:
        paths = args.fixture or sorted(str(p) for p in pathlib.Path("data/ci/fixtures").glob("*.json"))
        if not paths:
            print("no fixtures found — run scripts/capture_ci.py or pass --synthesize", file=sys.stderr)
            return 1
        runs = load_fixtures(paths)

    if args.direct:
        import asyncio

        n = asyncio.run(write_direct(runs))
        print(f"stored {n} new events directly")
        return 0

    from app.rag.hooks import sign  # signing for --via github

    sent = 0
    for events in runs:
        for event in events:
            if args.via == "github":
                body = json.dumps(event["payload"], ensure_ascii=False).encode("utf-8")
                code, text = _post(f"{args.base}/hooks/github", body, {
                    "X-GitHub-Event": event["kind"], "X-GitHub-Delivery": event["delivery_id"],
                    "X-Hub-Signature-256": sign(args.secret, body)})
                print(f"{code} {event['kind']:<13} {event['payload'].get('action', ''):<12} {text[:60]}")
            else:
                for report in status_bodies(event):
                    body = json.dumps(report, ensure_ascii=False).encode("utf-8")
                    code, text = _post(f"{args.base}/ci/status", body,
                                       {"authorization": f"Bearer {args.token}"} if args.token else {})
                    print(f"{code} {report.get('job') or 'run':<6} {str(report.get('stage') or ''):<36} {report.get('status')}")
            sent += 1
            if args.delay:
                time.sleep(args.delay)
    print(f"sent {sent} events")
    return 0


if __name__ == "__main__":
    sys.exit(main())

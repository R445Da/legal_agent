"""
Capture this repository's real GitHub Actions runs as replayable fixtures.

    python -m scripts.capture_ci                       # R445Da/legal_agent, last 5 runs
    python -m scripts.capture_ci --repo owner/name --runs 3 --out data/ci/fixtures

Uses the public REST API without authentication (fine for a public repo and
a handful of calls), and writes one JSON file per run in the shape
`scripts/replay_ci.py` replays: a list of `{"kind": "workflow_run" |
"workflow_job", "delivery_id", "payload"}` events, ordered as GitHub would have
sent them. No `gh` CLI, no token.
"""

import argparse
import json
import pathlib
import sys
import urllib.request

API = "https://api.github.com"


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "legal-agent-capture"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def _run_payload(repo: str, run: dict, action: str) -> dict:
    return {
        "action": action,
        "repository": {"full_name": repo},
        "workflow_run": {
            "id": run["id"], "name": run.get("name"), "run_number": run.get("run_number"),
            "head_sha": run.get("head_sha"), "head_branch": run.get("head_branch"), "event": run.get("event"),
            "status": "completed" if action == "completed" else ("in_progress" if action == "in_progress" else "queued"),
            "conclusion": run.get("conclusion") if action == "completed" else None,
            "html_url": run.get("html_url"), "run_started_at": run.get("run_started_at"),
            "updated_at": run.get("updated_at"), "path": run.get("path"),
        },
    }


def _job_payload(repo: str, run: dict, job: dict, action: str) -> dict:
    steps = [{"name": s.get("name"), "status": s.get("status"), "conclusion": s.get("conclusion"),
              "number": s.get("number"), "started_at": s.get("started_at"), "completed_at": s.get("completed_at")}
             for s in job.get("steps") or []]
    if action != "completed":
        steps = [{**s, "status": "queued" if action == "queued" else s["status"], "conclusion": None} for s in steps]
    return {
        "action": action,
        "repository": {"full_name": repo},
        "workflow_job": {
            "id": job["id"], "run_id": run["id"], "name": job.get("name"), "workflow_name": run.get("name"),
            "head_sha": run.get("head_sha"), "head_branch": run.get("head_branch"),
            "status": "completed" if action == "completed" else action,
            "conclusion": job.get("conclusion") if action == "completed" else None,
            "html_url": job.get("html_url"), "started_at": job.get("started_at"),
            "completed_at": job.get("completed_at") if action == "completed" else None,
            "steps": steps, "run_attempt": job.get("run_attempt"),
        },
    }


def capture(repo: str, n_runs: int) -> list[tuple[str, list[dict]]]:
    runs = _get(f"{API}/repos/{repo}/actions/runs?per_page={n_runs}").get("workflow_runs", [])
    out = []
    for run in runs:
        jobs = _get(f"{API}/repos/{repo}/actions/runs/{run['id']}/jobs?per_page=50").get("jobs", [])
        jobs.sort(key=lambda j: j.get("started_at") or "")
        events = [{"kind": "workflow_run", "delivery_id": f"cap:{run['id']}:run:requested",
                   "payload": _run_payload(repo, run, "requested")},
                  {"kind": "workflow_run", "delivery_id": f"cap:{run['id']}:run:in_progress",
                   "payload": _run_payload(repo, run, "in_progress")}]
        for job in jobs:
            for action in ("queued", "in_progress", "completed"):
                events.append({"kind": "workflow_job", "delivery_id": f"cap:{run['id']}:job:{job['id']}:{action}",
                               "payload": _job_payload(repo, run, job, action)})
        events.append({"kind": "workflow_run", "delivery_id": f"cap:{run['id']}:run:completed",
                       "payload": _run_payload(repo, run, "completed")})
        out.append((f"run-{run.get('run_number')}-{run.get('head_branch')}.json", events))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="R445Da/legal_agent")
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--out", default="data/ci/fixtures")
    args = ap.parse_args()
    out_dir = pathlib.Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, events in capture(args.repo, args.runs):
        path = out_dir / name
        path.write_text(json.dumps(events, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"wrote {path}  ({len(events)} events)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

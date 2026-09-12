#!/usr/bin/env bash
# Report a CI stage to the app so the dashboard shows the pipeline live.
#   scripts/ci_status.sh <job> <stage> <status> [conclusion]
#   e.g.  scripts/ci_status.sh test seed in_progress
#         scripts/ci_status.sh test finish completed success
# A no-op unless CI_STATUS_URL is set (a repository secret in GitHub Actions),
# and never fails the job: the pipeline must not depend on the demo receiver.
[ -z "${CI_STATUS_URL:-}" ] && exit 0
job="${1:-unknown}"; stage="${2:-step}"; status="${3:-in_progress}"; conclusion="${4:-}"
ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
url="${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY:-}/actions/runs/${GITHUB_RUN_ID:-}"
body=$(printf '{"run_id":"%s","run_number":"%s","job":"%s","stage":"%s","status":"%s","conclusion":"%s","sha":"%s","branch":"%s","url":"%s","ts":"%s","workflow":"%s","repo":"%s"}' \
  "${GITHUB_RUN_ID:-local}" "${GITHUB_RUN_NUMBER:-0}" "$job" "$stage" "$status" "$conclusion" \
  "${GITHUB_SHA:-}" "${GITHUB_REF_NAME:-}" "$url" "$ts" "${GITHUB_WORKFLOW:-docker}" "${GITHUB_REPOSITORY:-}")
curl -sS -m 5 -X POST "${CI_STATUS_URL%/}/ci/status" \
  -H "content-type: application/json" \
  -H "authorization: Bearer ${CI_STATUS_TOKEN:-}" \
  -d "$body" >/dev/null 2>&1 || true
exit 0

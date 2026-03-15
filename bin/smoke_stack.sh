#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNNER_PORT="${CODEXMGR_SMOKE_RUNNER_PORT:-8789}"
HOST_PORT="${CODEXMGR_SMOKE_HOST_PORT:-8792}"
RUNNER_API_KEY="${RUNNER_API_KEY:-codexmgr-smoke-key}"
SMOKE_NAME="smoke-v1-$$"
SHARED_HOME="$(mktemp -d "${TMPDIR:-/tmp}/codexmgr-smoke-home.XXXXXX")"
REPO_DIR="$(mktemp -d "${TMPDIR:-/tmp}/codexmgr-smoke-repo.XXXXXX")"
RUNNER_LOG="$(mktemp "${TMPDIR:-/tmp}/codexmgr-smoke-runner.XXXXXX.log")"

cleanup() {
  if [[ -n "${RUNNER_PID:-}" ]]; then
    kill "${RUNNER_PID}" >/dev/null 2>&1 || true
    wait "${RUNNER_PID}" >/dev/null 2>&1 || true
  fi
  (
    cd "${ROOT_DIR}"
    export CODEXMGR_HOST_HOME="${SHARED_HOME}"
    export CODEXMGR_CONTAINER_HOME="${SHARED_HOME}"
    export CODEXMGR_HOST_PORT="${HOST_PORT}"
    export RUNNER_BASE_URL="http://host.docker.internal:${RUNNER_PORT}"
    export RUNNER_API_KEY
    docker compose down >/dev/null 2>&1 || true
  )
  rm -rf "${SHARED_HOME}" "${REPO_DIR}"
  rm -f "${RUNNER_LOG}"
}
trap cleanup EXIT

wait_for_url() {
  local url="$1"
  for _ in $(seq 1 60); do
    if curl -fsS "${url}" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  echo "Timed out waiting for ${url}" >&2
  return 1
}

json_field() {
  local field="$1"
  python3 -c 'import json,sys; print(json.load(sys.stdin)[sys.argv[1]])' "${field}"
}

git -C "${REPO_DIR}" init -q
git -C "${REPO_DIR}" config user.email "smoke@example.com"
git -C "${REPO_DIR}" config user.name "Smoke Test"
printf 'smoke\n' > "${REPO_DIR}/README.md"
git -C "${REPO_DIR}" add README.md
git -C "${REPO_DIR}" commit -q -m "init"

(
  cd "${ROOT_DIR}"
  export CODEXMGR_HOME="${SHARED_HOME}"
  export RUNNER_API_KEY
  export CODEXMGR_CODEX_COMMAND='printf codexmgr-smoke-started\n; sleep 120'
  backend/.venv/bin/codexmgr runner --host 0.0.0.0 --port "${RUNNER_PORT}" >"${RUNNER_LOG}" 2>&1
) &
RUNNER_PID=$!

wait_for_url "http://127.0.0.1:${RUNNER_PORT}/health"

(
  cd "${ROOT_DIR}"
  export CODEXMGR_HOST_HOME="${SHARED_HOME}"
  export CODEXMGR_CONTAINER_HOME="${SHARED_HOME}"
  export CODEXMGR_HOST_PORT="${HOST_PORT}"
  export RUNNER_BASE_URL="http://host.docker.internal:${RUNNER_PORT}"
  export RUNNER_API_KEY
  docker compose up -d --build >/dev/null
)

wait_for_url "http://127.0.0.1:${HOST_PORT}/api/health"

START_PAYLOAD="$(curl -fsS "http://127.0.0.1:${HOST_PORT}/api/sessions/start" \
  -H 'Content-Type: application/json' \
  -d "{\"name\":\"${SMOKE_NAME}\",\"repoPath\":\"${REPO_DIR}\",\"profile\":\"read-only\",\"launch\":true}")"

SESSION_ID="$(printf '%s' "${START_PAYLOAD}" | json_field id)"
SESSION_STATUS="$(printf '%s' "${START_PAYLOAD}" | json_field status)"
if [[ "${SESSION_STATUS}" != "starting" ]]; then
  echo "Expected new session to start in 'starting', got '${SESSION_STATUS}'" >&2
  exit 1
fi

sleep 2
DETAIL_PAYLOAD="$(curl -fsS "http://127.0.0.1:${HOST_PORT}/api/sessions/${SESSION_ID}")"
DETAIL_STATUS="$(printf '%s' "${DETAIL_PAYLOAD}" | json_field status)"
if [[ "${DETAIL_STATUS}" != "running" && "${DETAIL_STATUS}" != "starting" ]]; then
  echo "Expected session status to be starting or running after launch, got '${DETAIL_STATUS}'" >&2
  exit 1
fi

LOG_PAYLOAD="$(curl -fsS "http://127.0.0.1:${HOST_PORT}/api/sessions/${SESSION_ID}/logs?tail=40")"
python3 - <<'PY' "${LOG_PAYLOAD}"
import json, sys
payload = json.loads(sys.argv[1])
if not any("codexmgr-smoke-started" in line for line in payload.get("lines", [])):
    raise SystemExit("Smoke output marker not found in session logs")
PY

OPEN_PAYLOAD="$(curl -fsS -X POST "http://127.0.0.1:${HOST_PORT}/api/sessions/${SESSION_ID}/open")"
python3 - <<'PY' "${OPEN_PAYLOAD}"
import json, sys
payload = json.loads(sys.argv[1])
command = payload.get("command", "")
if "tmux attach -t" not in command:
    raise SystemExit(f"Unexpected attach command: {command}")
PY

curl -fsS -X POST "http://127.0.0.1:${HOST_PORT}/api/sessions/${SESSION_ID}/stop" >/dev/null
BULK_PAYLOAD="$(curl -fsS -X POST "http://127.0.0.1:${HOST_PORT}/api/sessions/bulk-delete/stopped")"
python3 - <<'PY' "${BULK_PAYLOAD}" "${SMOKE_NAME}"
import json, sys
payload = json.loads(sys.argv[1])
name = sys.argv[2]
if name not in payload.get("deleted", []):
    raise SystemExit(f"Expected stopped-session cleanup to delete {name}, got {payload}")
PY

SUMMARY_PAYLOAD="$(curl -fsS "http://127.0.0.1:${HOST_PORT}/api/summary")"
printf 'Smoke passed. Summary: %s\n' "${SUMMARY_PAYLOAD}"

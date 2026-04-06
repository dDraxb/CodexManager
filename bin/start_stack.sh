#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNNER_HOST="${RUNNER_HOST:-0.0.0.0}"
RUNNER_PORT="${RUNNER_PORT:-8788}"
RUNNER_SESSION_NAME="${CODEXMGR_RUNNER_SESSION_NAME:-codexmgr-host-runner}"
CODEXMGR_HOST_HOME="${CODEXMGR_HOST_HOME:-${CODEXMGR_HOME:-$HOME/.codexmgr}}"
CODEXMGR_CONTAINER_HOME="${CODEXMGR_CONTAINER_HOME:-${CODEXMGR_HOST_HOME}}"
CODEXMGR_HOST_PORT="${CODEXMGR_HOST_PORT:-8791}"
RUNNER_LOG_DIR="${CODEXMGR_HOST_HOME}/logs"
RUNNER_LOG_PATH="${RUNNER_LOG_DIR}/runner.log"
RUNNER_KEY_PATH="${CODEXMGR_HOST_HOME}/runner_api_key"

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

mkdir -p "${CODEXMGR_HOST_HOME}" "${RUNNER_LOG_DIR}"

if [[ -n "${RUNNER_API_KEY:-}" ]]; then
  printf '%s\n' "${RUNNER_API_KEY}" > "${RUNNER_KEY_PATH}"
elif [[ ! -s "${RUNNER_KEY_PATH}" ]]; then
  printf '%s\n' "dev-runner-key" > "${RUNNER_KEY_PATH}"
fi

RUNNER_API_KEY="$(tr -d '\r\n' < "${RUNNER_KEY_PATH}")"
RUNNER_BASE_URL="${RUNNER_BASE_URL:-http://host.docker.internal:${RUNNER_PORT}}"

if ! command -v tmux >/dev/null 2>&1; then
  echo "tmux is required to run the host runner durably." >&2
  exit 1
fi

if ! tmux has-session -t "${RUNNER_SESSION_NAME}" 2>/dev/null; then
  tmux new-session -d -s "${RUNNER_SESSION_NAME}" \
    "cd ${ROOT_DIR} && export CODEXMGR_HOME='${CODEXMGR_HOST_HOME}' RUNNER_API_KEY='${RUNNER_API_KEY}' && exec backend/.venv/bin/codexmgr runner --host '${RUNNER_HOST}' --port '${RUNNER_PORT}' >>'${RUNNER_LOG_PATH}' 2>&1"
fi

wait_for_url "http://127.0.0.1:${RUNNER_PORT}/health"

(
  cd "${ROOT_DIR}"
  export CODEXMGR_HOST_HOME
  export CODEXMGR_CONTAINER_HOME
  export CODEXMGR_HOST_PORT
  export RUNNER_BASE_URL
  export RUNNER_API_KEY
  docker compose up -d --build codexmgr
)

wait_for_url "http://127.0.0.1:${CODEXMGR_HOST_PORT}/api/health"

cat <<EOF
codex-manager stack started
- dashboard: http://127.0.0.1:${CODEXMGR_HOST_PORT}/
- runner session: ${RUNNER_SESSION_NAME}
- runner log: ${RUNNER_LOG_PATH}
- runner key: ${RUNNER_KEY_PATH}
EOF

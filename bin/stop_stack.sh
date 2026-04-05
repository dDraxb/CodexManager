#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNNER_SESSION_NAME="${CODEXMGR_RUNNER_SESSION_NAME:-codexmgr-host-runner}"

(
  cd "${ROOT_DIR}"
  docker compose down
)

if command -v tmux >/dev/null 2>&1 && tmux has-session -t "${RUNNER_SESSION_NAME}" 2>/dev/null; then
  tmux kill-session -t "${RUNNER_SESSION_NAME}"
fi

echo "codex-manager stack stopped"

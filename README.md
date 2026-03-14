# Codex Session Manager

Local-first control plane for Codex sessions on macOS.

## Implemented V1 Scope

- Managed sessions with optional dedicated git worktree/branch
- Adopted sessions with reduced observability mode
- Canonical local session/event persistence in SQLite (`~/.codexmgr` or `CODEXMGR_HOME`)
- CLI contract: `start`, `list`, `inspect`, `open`, `stop`, `adopt`, `resume`, `ui`
- Deterministic reconciliation monitor (tmux presence + log idle + git change counts)
- Local FastAPI endpoints for dashboard + actions
- React/Vite dashboard with session grid, detail panel, logs, events, and quick actions

## Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

codexmgr start --name vat-fix --repo /path/to/repo --profile safe-edit --no-launch
codexmgr list
codexmgr inspect vat-fix
codexmgr stop vat-fix
codexmgr ui
```

`codexmgr ui` serves API and, if present, the frontend build from `frontend/dist`.

By default writable sessions do not create a separate worktree/branch.
Enable worktree mode explicitly when you want branch isolation:

```bash
codexmgr start --name vat-fix --repo /path/to/repo --profile safe-edit --create-worktree
```

If your folder is not a git repository yet, use:

```bash
codexmgr start --name vat-fix --repo /path/to/folder --profile safe-edit --auto-init-git
```

If you want every managed session to leave a starter entry in `CHANGELOG.md`, use:

```bash
codexmgr start --name vat-fix --repo /path/to/repo --profile safe-edit --require-changelog
```

## Frontend

```bash
cd frontend
npm install
npm run build
```

For local development (API proxied to `http://127.0.0.1:8790`):

```bash
npm run dev
```

## Docker

Run UI + API as a persistent container:

```bash
docker compose up -d --build
```

Open:

```text
http://127.0.0.1:8791/
```

To keep execution on the host while the dashboard runs in Docker, start the host runner first:

```bash
cd backend
source .venv/bin/activate
export RUNNER_API_KEY=dev-runner-key
codexmgr runner --host 0.0.0.0 --port 8788
```

Then point the containerized API at that host runner:

```bash
export CODEXMGR_HOST_HOME=/tmp/codexmgr-shared
export CODEXMGR_CONTAINER_HOME=/tmp/codexmgr-shared
mkdir -p "$CODEXMGR_HOST_HOME"
export RUNNER_BASE_URL=http://host.docker.internal:8788
export RUNNER_API_KEY=dev-runner-key
docker compose up -d --build
```

In this mode the dashboard/API stays in Docker, while `tmux`, `codex`, and git worktree operations execute on the host runner. The shared `CODEXMGR_HOME` path keeps logs and session artifacts readable from both sides.

If you want to use host repos from inside the container, add a repo mount override:

```bash
export CODEXMGR_HOST_REPO_ROOT=/Users/davidblom/Projects
export CODEXMGR_CONTAINER_REPO_ROOT=/Users/davidblom/Projects
docker compose -f docker-compose.yml -f docker-compose.repos.yml up -d --build
```

This keeps host-path mapping explicit and avoids hardcoded machine-specific paths.

Stop:

```bash
docker compose down
```

## Notes

- `tmux` is required for live launch/open/resume behavior.
- When `RUNNER_BASE_URL` is set, execution is delegated to the runner service instead of the API process.
- The dashboard now exposes bulk cleanup for stopped sessions and test-named sessions, plus an archive view for terminal states.
- Without `tmux`, sessions can still be tracked, inspected, and managed as records.
- Set `CODEXMGR_HOME=/tmp/codexmgr-dev` to isolate local test data.

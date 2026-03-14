# Backend

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
pip install pytest httpx
```

## CLI

```bash
codexmgr start --name vat-fix --repo /path/to/repo --profile safe-edit --no-launch
codexmgr start --name isolated-task --repo /path/to/repo --profile safe-edit --create-worktree --no-launch
codexmgr start --name new-task --repo /path/to/non-git-folder --profile safe-edit --auto-init-git --no-launch
codexmgr start --name tracked-task --repo /path/to/repo --profile safe-edit --require-changelog --no-launch
codexmgr list --json
codexmgr inspect vat-fix
codexmgr adopt --name imported --codex-session cdx_123 --repo /path/to/repo
codexmgr stop vat-fix
codexmgr ui
codexmgr runner --host 0.0.0.0 --port 8788
```

## Docker Control Plane + Host Runner

Run the execution runner on the host:

```bash
export RUNNER_API_KEY=dev-runner-key
codexmgr runner --host 0.0.0.0 --port 8788
```

Then run the dashboard/API in Docker with:

```bash
export CODEXMGR_HOST_HOME=/tmp/codexmgr-shared
export CODEXMGR_CONTAINER_HOME=/tmp/codexmgr-shared
mkdir -p "$CODEXMGR_HOST_HOME"
export RUNNER_BASE_URL=http://host.docker.internal:8788
export RUNNER_API_KEY=dev-runner-key
docker compose up -d --build
```

## Tests

```bash
pytest -q
```

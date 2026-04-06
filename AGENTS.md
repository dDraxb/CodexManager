# AGENTS

## Local Stack Commands

For this repo, do not restart the dashboard with plain Docker commands like:

```bash
docker compose up -d --build codexmgr
```

That path can start the container without the shared runner API key and break the app with:

- `invalid runner api key`
- `Request failed (500)`

Always use the durable stack scripts instead:

```bash
./bin/start_stack.sh
./bin/restart_stack.sh
./bin/stop_stack.sh
```

These scripts keep the host runner and Docker dashboard aligned on:

- the shared `CODEXMGR_HOME`
- the persisted runner key at `~/.codexmgr/runner_api_key`
- the tmux-backed host runner session

If the UI starts throwing runner auth or 500 errors after a rebuild, recover with:

```bash
./bin/restart_stack.sh
```

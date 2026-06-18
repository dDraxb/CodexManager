# AGENTS

# Agent Startup Guide

Use this file to restart quickly in a fresh context. The README is the source
of truth for repo intent and layout.

## Startup

1. Read `README.md`.
2. Read `CHANGELOG.md` and `plans.md` for current phase and recent changes.

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

## Working Rules
- Reply with only essential information.
- Explain only when asked; otherwise report what changed, what was checked, and the commit.
- Make only high-confidence changes.
- Update `CHANGELOG.md` for documentation or model changes.
- UPDATE `README.md` or `AGENTS.md` when a change impacts the documentation
- Commit regularly using the existing history format, for example `YYMMDD-HHMM: short factual subject`.
- Keep edits scoped. Do not duplicate large sections already covered by README or changelog
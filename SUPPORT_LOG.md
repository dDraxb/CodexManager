# Support Log

## 2026-05-27 - Claude Code support feasibility

This tracks adjacent execution-provider ideas that are not part of the canonical V2 layer plan yet.

### Question

How hard would it be to add Claude Code support alongside Codex?

### Current read

Likely moderate. The existing manager already has the right outer shape: a dashboard, a host runner API, tmux-backed live sessions, local history import, config/asset management, validation telemetry, handoffs, and automation follow-ups. The harder part is not starting `claude`; it is avoiding Codex-specific assumptions leaking through the data model, UI labels, resume logic, and environment management surfaces.

### Useful Claude Code capabilities

- Claude Code has a CLI that can start interactive sessions, run print-mode prompts, continue the latest conversation, resume by session id or name, attach to background sessions, and expose background-agent logs.
- Claude Code supports structured non-interactive output with `--output-format json` and `--output-format stream-json`.
- Claude Code persists session history locally under `~/.claude/projects/<encoded-cwd>/*.jsonl`; resuming depends on using the matching working directory and having that session file on the current machine.
- Claude Code has hook events for session start/end, prompts, tool use, permission requests, idle/notification events, compaction, file changes, and config changes. Hooks can provide structured JSON context to external handlers.
- Claude Code has native concepts that overlap with this manager's roadmap: background sessions, agents, MCP, plugins, permission modes, worktrees, resume/fork, and local transcript enumeration.

Sources checked:
- https://code.claude.com/docs/en/cli-usage
- https://code.claude.com/docs/en/agent-sdk/sessions
- https://code.claude.com/docs/en/hooks

### Suggested architecture

Do not bolt Claude Code into `codex_*` services directly. Add an execution-provider boundary first:

- `provider = codex | claude`
- provider-specific session metadata columns or a JSON metadata field
- provider-specific runner commands for start, attach, resume, logs, history scan, config scan
- neutral UI language where possible: "agent history", "provider config", "session transcript"
- provider-specific environment tabs for Codex assets and Claude assets

Codex can remain the default provider while Claude support is introduced behind capability checks.

### First implementation slice

1. Add provider metadata to sessions without changing current Codex behavior. Done in the provider-foundation commit.
2. Add a Claude runner adapter that can detect `claude`, report version/auth status if available, and build a dry-run start command.
3. Add Claude history discovery for `~/.claude/projects`.
4. Add a create-session provider selector in the dashboard, initially defaulting to Codex.
5. Only after that, add live Claude launch/resume/attach behavior.

### Provider foundation status

The manager now has the first provider boundary:

- sessions persist `provider`, defaulting to `codex`
- existing sessions migrate to `codex`
- the API exposes a provider registry with Codex supported and Claude Code planned
- managed/adopted session creation accepts provider metadata but rejects unsupported providers before creating session records
- dashboard create/adopt forms expose the provider selector while keeping unsupported providers disabled
- automation follow-up sessions inherit their parent provider
- Codex history linking, resume-point lookup, and automatic resume stay explicitly Codex-only

### Risk notes

- Claude Code session resume is cwd-sensitive, so manager-owned worktrees and history adoption need careful mapping.
- Claude Code's settings, hooks, plugins, agents, and permissions should not be treated as equivalent to Codex config/presets/skills.
- If both providers are supported, automation prompts and handoffs should stay provider-neutral until launch time.
- Full multi-provider support probably belongs to a new cross-provider track rather than the existing V2 layer list.

### Effort estimate

- Basic detection and planning UI: small.
- Claude history indexing and dry-run session creation: small to medium.
- Live managed Claude sessions with tmux/log/resume parity: medium.
- First-class Claude environment management and provider-neutral automation: medium to large.

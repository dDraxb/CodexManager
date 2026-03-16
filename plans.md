 # Codex Session Manager — Unified Plan

## Purpose
This is the single canonical plan for the project.

It replaces the old split between `plans.md` and `NEXT_SESSION_PLAN.md`.
It should describe:
- what the product is
- what is already implemented
- what is still incomplete
- what the next serious expansion areas are

---

## Product Definition
Codex Session Manager is a local-first control plane for Codex coding sessions.

Core model:

**Manager -> runner -> tmux session -> Codex CLI process -> repo/worktree**

Design intent:
- the manager owns session identity and observability
- tmux is the durable execution layer
- Warp is a viewer/interaction layer, not the source of truth
- execution should happen where `tmux`, `codex`, and repo access actually exist

---

## Current Architecture

### Control plane
- FastAPI backend
- React/Vite dashboard
- Typer CLI
- SQLite session/event store

### Execution plane
- `RunnerClient` abstraction
- `LocalRunnerClient` for non-docker/local execution
- `RemoteRunnerClient` for Docker dashboard -> host runner execution
- host runner API for tmux/git/session operations

### Current deployment model
- dashboard/API can run locally or in Docker
- execution can stay on the host
- shared manager home keeps logs and session artifacts visible from both sides

---

## What Is Implemented

### Session lifecycle
- start managed sessions
- adopt existing Codex sessions
- inspect/list sessions
- copy attach command
- resume sessions
- stop sessions
- delete sessions
- bulk delete stopped sessions
- bulk delete test-named sessions

### Session metadata and observability
- repo path, cwd, branch, prompt, profile, approval policy
- changed file count and preview
- event log
- output tail
- managed vs adopted session mode
- attachment presence (`attached` / `detached`)
- output activity tracking via pane fingerprinting
- basic inferred validation telemetry for tests and lint from recent session output

### Status model
Implemented statuses:
- `created`
- `starting`
- `running`
- `waiting_input`
- `idle`
- `finished`
- `failed`
- `stopped`
- `lost`

Current status behavior is substantially improved:
- new sessions stay `starting` until real activity is observed
- attach/open does not directly force `running`
- idle sessions wake back to `running` on actual new output
- repeated same-status event spam is suppressed
- missing tmux sessions move managed sessions to `lost`

### Repo/worktree behavior
- no automatic worktree/branch creation by default
- optional worktree creation for writable sessions
- `auto-init-git` for plain folders
- branch and changed-file refresh

### Changelog policy
- `require_changelog` flag exists
- `CHANGELOG.md` can be created/appended on session start
- visible in backend, CLI, and UI

### Frontend/dashboard
- dashboard is functional and actively used
- archive view exists
- cleanup controls exist
- create/adopt/cleanup controls are now organized in one integrated tabbed module
- selected session shows status, attachment state, repo state, activity, events, and output

### Docker + host runner split
- host runner command exists
- Docker dashboard can route execution to host runner
- docs exist for this mode

### Validation already done
- unit and integration tests for runner abstraction and status transitions
- tests for CLI/API flows
- repeated live smoke validation against real tmux/docker flows
- repeatable full-stack smoke script for Docker dashboard + host runner mode

---

## What Was the Key Architectural Milestone
The most important completed shift was separating orchestration from execution.

Session services now orchestrate:
- DB updates
- lifecycle transitions
- event recording
- API/CLI behavior

Runner implementations now own:
- tmux interaction
- shell launch
- repo path resolution
- git/worktree operations
- pane capture / attachment checks

This was the main unresolved issue in the older handoff and is now done.

---

## What Is Still Incomplete

These are real remaining items, not already-finished work.

### 1. Better reopen workflow ergonomics
Current behavior is:
- copy attach command
- user pastes into terminal

That is reliable, but still a low-level operator flow.
Still possible:
- better Warp-oriented reopen helpers
- optional terminal-launch integration
- easier one-click resume/open flows where appropriate

### 2. More polished frontend information architecture
The dashboard is functional, but there is still room to improve:
- visual hierarchy
- density management
- session detail layout
- better use of charts and summaries
- less operator friction for frequent actions

### 3. Better archival and history model
We currently treat terminal states and archive view pragmatically.
Possible future work:
- explicit archive/unarchive model
- session retention policies
- searchable historical sessions
- better distinction between “completed”, “failed”, and “abandoned”

### 4. Deeper validation intelligence
Basic validation telemetry now exists, but the more ambitious version is still open:
- repo-specific validation recipes
- durable validation history
- richer pass/fail summaries
- “changed since last green run” logic
- broader engineering quality signals

---

## Future Product Expansions

This is the area that has barely been scratched. The current product is a solid control plane foundation, not the full ceiling.

## V2 Vision

V2 should turn the manager from a session launcher/tracker into an actual engineering operations surface for AI-assisted development.

The right mental model is not:
- “a nicer tmux wrapper”

The right mental model is:
- “a control plane for parallel coding work”

That means V2 should help answer higher-level questions:
- what is each Codex session actually doing right now
- which sessions are healthy versus risky
- which repos have work in progress that is unfinished or conflicting
- what validation has or has not been run
- where human attention is required next
- how work should be handed off, resumed, or concluded

The V1 foundation already gives us:
- a session identity model
- a runner boundary
- a dashboard
- event and output capture
- deterministic status signals

V2 should build on that foundation in a clear priority order.

### V2 Priority 1 - True Codex history resume and adoption

This is the top V2 item.

The current product is very good at reattaching to a live tmux-backed Codex process.
It is much weaker at reconstructing work once that original process is gone.

That distinction matters:
- `tmux attach` reconnects to the exact running Codex process
- `codex resume <session-id>` starts a new Codex process and asks Codex itself to restore prior history

Today, manager-created sessions are strongest in the first mode.
Adopted sessions and older historical sessions depend on the second mode.
That creates an inconsistency:
- live sessions feel seamless
- older sessions are harder to re-enter cleanly
- users with many prior Codex sessions do not yet get a first-class import/adopt/resume experience

V2 should close that gap directly.

The product goal is:
- every important session should be resumable from the manager even after the original tmux process is gone
- older Codex history should be importable and adoptable in a structured way
- the manager should make a clear distinction between “attach to live process” and “resume from Codex history”

This requires several concrete capabilities:

#### Persist the real Codex session id for managed sessions

Right now, manager-created sessions have a manager session id and a tmux session name, but the real underlying Codex conversation/session id is not yet a first-class captured field for the managed-session lifecycle.

V2 should:
- detect the Codex session id shortly after managed-session startup
- persist it on the manager session record
- keep it visible in the UI and CLI when available

That is the key enabler for historical resume after tmux is gone.

#### Separate two different reopen actions in the product

The manager should stop treating all “resume/open” flows as conceptually the same.

It should expose two distinct actions:
- `Attach live session`
  Reconnect to an existing tmux-backed Codex process.
- `Resume from Codex history`
  Launch a fresh Codex process that resumes from the stored Codex session id.

This is important because the user experience is different:
- live attach restores the exact interactive process state
- historical resume reconstructs from Codex’s saved history and may involve Codex-native resume UI behavior

#### First-class historical adoption/import

The manager should become good at taking previously created Codex sessions and making them manageable.

That means:
- import or browse session history from `CODEX_HOME`
- inspect prior session metadata before adoption
- adopt older sessions into the manager with clear provenance
- support resume flows for sessions that were never originally launched by the manager

This is especially important for users who already have many valuable prior Codex sessions and want the manager to become their single control surface.

#### Better operator semantics around continuity

The product should make clear what kind of continuity the user is getting:
- exact live continuation
- historical conversational continuation
- manager-local metadata continuity

This removes a lot of current ambiguity around ids and “what exactly am I reopening?”

#### Reliability requirements

This feature should not be implemented as a brittle one-off parser.
It needs a defensible approach for:
- detecting and persisting Codex session ids
- handling missing or unavailable ids gracefully
- surviving changes in Codex output format where possible
- testing both live attach and historical resume flows

This is not a V1 blocker, but it is the most important next capability because it unlocks the manager as a real home for both new work and prior work.

After this top-priority item, V2 should continue in these broader layers:
- execution intelligence
- engineering workflow intelligence
- collaboration/handoff intelligence
- historical analysis and policy

### V2 Layer 1 - Execution intelligence

Right now the manager can tell whether a session is attached, detached, idle, running, lost, or starting. That is useful, but still very low-level.

V2 should infer richer, operator-meaningful activity phases such as:
- planning
- reading code
- editing
- testing
- waiting for approval
- waiting for user input
- blocked on environment
- completed but unreviewed

This does not need to depend on “AI magic” first. It can start from structured heuristics:
- recent pane/output markers
- recognized tool/test command patterns
- file-change bursts
- exit codes
- repo state changes
- approval prompts

Why this matters:
- `running` is too coarse
- `idle` does not explain why the session is inactive
- the user needs to know which sessions are productive, blocked, or forgotten

This layer should eventually power:
- better status badges
- more meaningful event types
- session health scoring
- clearer “needs attention” prioritization

### V2 Layer 2 - Validation and engineering workflow telemetry

One of the biggest missing pieces in the current product is engineering confidence.

Today, the dashboard can show changed files and basic status, but it does not yet reliably answer:
- were tests run
- did lint pass
- was a build attempted
- which validation recipe belongs to this repo
- whether a session is ready for human review

V2 should add first-class validation tracking.

That means:
- define validation recipes per repo or repo type
- record validation runs as structured events
- store latest pass/fail state per validation class
- keep timestamped validation history per session
- surface “code changed since last green validation”

Examples:
- for a Node repo: `npm test`, `npm run lint`, `npm run build`
- for a Python repo: `pytest`, `ruff`, `mypy`
- for a PHP repo: `phpunit`, `phpstan`, `ecs`

This should not be hardcoded globally. The right design is:
- repo-level or preset-based validation definitions
- explicit session metadata for which validations matter
- UI surfaces that make validation state visible without needing to inspect raw logs

This is probably the single highest-value V2 feature area because it moves the tool from observability toward engineering assurance.

### V2 Layer 3 - Git and repo intelligence

The manager currently knows branch and changed file counts, but it does not yet understand the quality or risk of repo state deeply enough.

V2 should make the session manager much more git-aware:
- summarize the scope of diffs
- detect risky repo state before session start
- identify work on protected branches
- warn about dirty repos before launch
- identify overlapping edits across multiple sessions
- show whether a session is isolated in a worktree or touching the main repo directly

This should eventually support:
- better safety defaults
- branch/worktree policy decisions
- merge/handoff readiness checks
- conflict awareness across sessions in the same repo

Examples of useful questions V2 should answer:
- are two active sessions editing the same repo at the same time
- did a session make changes directly on `main`
- is this repo dirtier now than when the session started
- has the session diverged significantly from its initial branch state

This layer turns the manager into something more operationally trustworthy for real engineering work.

### V2 Layer 4 - Collaboration and handoff

The current product tracks sessions, but it does not yet model work handoff as a first-class concept.

V2 should add structured handoff support.

That means each session can eventually have:
- a goal summary
- a current state summary
- unresolved questions
- validation state
- files touched
- suggested next actions
- final disposition when stopped or archived

This becomes valuable in multiple cases:
- user pauses work and resumes later
- user compares several sessions attacking the same problem
- user wants to archive a session but retain its value
- user wants a quick “what happened here” summary without reopening the full tmux context

Over time, this should support:
- stop-time session summaries
- archive summaries
- handoff notes
- human review checklists
- “resume briefing” when reopening a dormant session

This is especially important if the tool evolves beyond one-person local use.

### V2 Layer 5 - History, archive, search, and analytics

V1 mostly treats history as stored rows plus event logs.

V2 should make past work explorable and useful.

This means:
- searchable session history
- filtering by repo, branch, profile, outcome, date, or validation state
- archived-session summaries
- trend views over time
- identifying repeat failure patterns
- finding abandoned work that keeps resurfacing

Examples of useful historical questions:
- which repos generate the most failed or abandoned sessions
- how often do sessions go idle without completion
- which validation step fails most often
- which tasks tend to require the most human intervention

This layer is where the product starts becoming a real engineering insight tool, not just a live dashboard.

### V2 Layer 6 - Policies, presets, and repo-specific behavior

The current product has a few simple knobs:
- permissions profile
- optional worktree creation
- optional changelog enforcement

V2 should turn these into policy and preset systems.

Examples:
- repo A requires changelog plus tests before completion
- repo B forbids direct work on protected branches
- repo C always uses dedicated worktrees for writable sessions
- “safe backend fix” preset
- “risky refactor” preset
- “read-only investigation” preset

This gives the tool two major advantages:
- safer operation with fewer manual decisions
- faster session setup with meaningful defaults

The right implementation direction is:
- explicit preset definitions
- repo matching rules
- policy checks surfaced as actionable UI warnings rather than silent behavior

### V2 Layer 6.5 - Codex environment and asset management

This is the biggest adjacent strength we should absorb from desktop-style Codex managers.

Right now our product is strong at live session operations, but weak at managing the broader Codex environment around those sessions.

V2 should add first-class management for the Codex asset surface itself:
- `CODEX_HOME/config.toml`
- workspace `.codex/config.toml`
- prompts
- rules
- skills
- MCP server definitions
- local session history stored under `CODEX_HOME`

This should not replace the session-control focus of the product. It should extend it.

The right product shape is:
- session operations remain the center
- Codex environment management becomes a second major capability area

Key features to add:

#### Safe config editing
- simple editor for common scalar settings
- advanced editor for nested values
- raw editing mode for full control
- diff preview before apply
- automatic backup and restore
- atomic writes with validation

This matters because Codex session behavior is heavily influenced by config, and today the manager does not give enough visibility or safety around those files.

#### Presets and configuration libraries
- curated built-in presets
- user-saved presets
- repo-specific presets
- preview before apply
- partial overlay vs full replace semantics

This turns configuration from ad hoc tweaking into a repeatable operational tool.

Examples:
- a “safe investigation” preset
- a “high-autonomy refactor” preset
- a repo-specific backend preset
- a personal low-risk default profile

#### Skills management
- browse global skills under `CODEX_HOME`
- browse repo-scoped skills under `.codex/skills`
- edit `SKILL.md` and supporting files
- create/delete skills from the UI
- later: install/import skills from trusted registries or repos

This fits our product very naturally because skills directly affect how sessions behave, but today the manager does not own or expose that capability.

#### MCP and tool integration management
- inspect configured MCP/tool entries
- enable/disable them safely
- edit/update definitions with validation
- see which sessions or presets depend on them

This is especially useful once we start introducing repo presets and execution policies.

#### Local session history import
- scan `CODEX_HOME/sessions`
- surface historical Codex sessions that were not originally manager-controlled
- attach richer metadata to imported history
- optionally allow “adopt from history” workflows

This is an important bridge between the broader Codex ecosystem and the manager’s own canonical session model.

The core rule here is:
- imported CODEX_HOME history is useful context
- manager-native session identity still remains canonical for active orchestration

### V2 Layer 7 - Multi-host and distributed execution

The runner split now makes this feasible, but it is not yet a product feature.

V2 can expand from:
- one dashboard, one host runner

to:
- one dashboard, multiple host runners

That would allow:
- host labels
- machine selection at session start
- host-specific repo visibility
- pooled execution environments
- cross-machine session tracking

This becomes relevant if the tool grows into:
- multiple Macs
- personal workstation plus server
- specialized build/test hosts

The important point is that the architecture now makes this possible without redesigning the whole system again.

### V2 Layer 8 - Notifications and background operations

Right now the dashboard is primarily poll-driven and user-observed.

V2 should support more active operational assistance:
- desktop notifications when a session needs input
- notifications when validation fails
- reminders for stale detached sessions
- background reconciliation daemon
- smarter polling and backoff behavior

This is not glamorous, but it is high leverage. The tool becomes much more useful when it can pull the operator’s attention only when needed.

---

### Execution intelligence
- detect structured activity markers from Codex output
- infer current phase: planning, editing, testing, waiting, blocked
- session health scoring
- “why is this session idle?” diagnostics

### Validation orchestration
- run named validation recipes per repo
- attach test/lint/build commands to session types
- automatic post-change validation
- visible pass/fail trend per session
- repo-specific validation presets

### Git awareness
- richer diff summaries
- commit/branch hygiene suggestions
- detect uncommitted risky state before session start
- smarter worktree policies by profile/repo
- optional PR prep or handoff summaries

### Collaboration and handoff
- explicit handoff notes per session
- session summaries on stop/archive
- compare two sessions working in the same repo
- identify conflicting work across sessions
- attach changelog / notes / decisions to session history

### UX and operator tooling
- keyboard-driven dashboard actions
- better filtering and saved views
- session pinning / priority / ownership markers
- “needs attention” drill-down
- richer event timeline with typed events and grouping

### Notifications and background monitoring
- desktop notifications when a session needs input or fails
- smarter polling/backoff rules
- optional background reconciler daemon
- stale-session reminders

### Remote / multi-host future
- multiple host runners
- host labels / pool selection
- per-host repo visibility
- distributed session control across machines

### Policy and safety
- repo-specific startup policies
- permission-profile templates
- required validation before marking complete
- session start guards for dirty repos or protected branches

### Search and analytics
- full-text search across events/log tails
- per-repo session history
- trend analysis: duration, churn, failure rate, validations
- identify the repos/tasks that generate the most abandoned work

### Desktop packaging and operator UX
- optional packaged desktop app shell later
- local file-integrated workflows for config, skills, and backups
- richer offline-first experience
- stronger operator ergonomics around local Codex assets

---

## Near-Term Roadmap

### Phase A - Stabilize current V1
- keep refining status/attachment correctness
- tighten Docker dashboard + host runner reliability
- add more automated end-to-end coverage
- continue cleaning frontend layout and action clarity

### Phase B - Improve operator value
- richer validation/test telemetry
- better event taxonomy
- better session summaries
- stronger archive/history experience
- begin Codex config/skills/preset management layer

### Phase C - Expand into a true engineering control plane
- multi-host runners
- policy engine
- repo-specific automation
- search/history/analytics
- stronger handoff and collaboration features
- full Codex environment management and preset ecosystem

---

## Definition of Done for Current V1 Foundation
The current foundation should be considered complete when:
- Docker dashboard + host runner mode is reliable
- session status transitions are stable and understandable
- create/adopt/cleanup flows are operationally clear
- bulk cleanup and archive flows are reliable
- changelog policy works
- runner boundary remains clean
- no recurring UI/backend regressions remain in normal daily use

That does **not** mean the product is “finished.”
It means the base platform is ready for the next layer of capabilities.

---

## Guidance for Future Work
- Keep a strict control-plane vs execution-plane split.
- Do not reintroduce direct tmux/git/shell orchestration into session services.
- Prefer adding capability through runner contracts, typed session metadata, and explicit events.
- Treat dashboard polish as product work, not cosmetic afterthought.
- When adding new features, always decide whether they belong to:
  - session orchestration
  - execution runner
  - observability model
  - UI/operator workflow

---

## Practical Next Bets
If work continues immediately, the highest-value next candidates are:

1. Add structured validation/test telemetry.
2. Add formal Docker + host runner E2E automation.
3. Improve the session detail/dashboard information architecture.
4. Add historical summaries and better archive semantics.
5. Design repo-specific policies and validation presets.
6. Design safe Codex config/skills/preset management as a first-class V2 track.
- `stopped`
- `lost`

### Meaning notes
- `waiting_input`: the session appears to be awaiting user input or approval
- `idle`: process is alive but little/no recent activity is seen
- `lost`: the manager expected the session to exist but cannot reconcile tmux/process state

---

## Permission Profiles
V1 should use explicit permission profiles instead of loose ad hoc flags.

### `read-only`
- inspect files
- no writes
- read-only shell commands only
- no worktree required by default

### `safe-edit`
- edit files within a dedicated worktree
- run tests and lint
- block destructive machine-wide commands
- ask approval for risky operations

### `full-agent`
- broader shell access within repo boundary
- writable worktree
- run project commands freely inside policy
- still protect clearly dangerous global operations

These profiles should be visible in both CLI and UI.

---

## CLI Contract
The CLI is the main terminal control surface.

### Core commands
```bash
codexmgr start --name vat-fix --repo ~/code/shop --profile safe-edit --prompt "Fix VAT rounding"
codexmgr list
codexmgr list --json
codexmgr inspect vat-fix
codexmgr open vat-fix
codexmgr stop vat-fix
codexmgr adopt --name imported-fix --codex-session cdx_123 --repo ~/code/shop
codexmgr resume vat-fix
codexmgr ui
```

### Command expectations

#### `start`
Creates a managed session.

Expected behavior:
- create DB record
- optionally create worktree
- create branch
- create tmux session
- launch Codex with selected profile
- capture output log
- store Codex session id if available
- begin monitor tracking

#### `list`
Shows all sessions.

Expected behavior:
- human-readable table by default
- JSON when requested

#### `inspect`
Shows details for one session.

Expected behavior:
- metadata
- recent output tail
- changed files preview
- current status
- timestamps

#### `open`
Attaches to the session.

Expected behavior:
- attach to tmux
- optionally launch Warp if configured
- otherwise print the attach command

#### `stop`
Stops a managed session.

Expected behavior:
- graceful termination first
- harder stop if needed
- final status/timestamps updated

#### `adopt`
Registers an existing Codex session id.

Expected behavior:
- create local record
- require repo path
- mark as adopted
- clearly indicate reduced observability

#### `resume`
Resumes or reopens a known session.

Expected behavior:
- if tmux exists, reattach
- if Codex supports native resume, use stored Codex session id
- distinguish between tmux reopen and Codex conversation resume

#### `ui`
Starts the local dashboard.

Expected behavior:
- start local API/server
- serve frontend
- print local URL

---

## Local API Plan
A lightweight local API should back the dashboard.

### Suggested endpoints
- `GET /api/health`
- `GET /api/summary`
- `GET /api/sessions`
- `GET /api/sessions/{id}`
- `GET /api/sessions/{id}/logs?tail=200`
- `GET /api/sessions/{id}/events`
- `POST /api/sessions/start`
- `POST /api/sessions/{id}/open`
- `POST /api/sessions/{id}/stop`
- `POST /api/sessions/{id}/resume`
- `POST /api/sessions/adopt`

### API philosophy
- stable JSON shape
- explicit fields
- server-side derived summaries
- no frontend need to parse raw logs to infer state

---

## Monitoring Model
The V1 manager should be reliable rather than clever.

### Deterministic signals to monitor
- tmux session exists / missing
- process alive / exited
- exit code if available
- last output timestamp
- changed file count
- dirty/clean git state
- current branch
- recent recognized command/test markers

### Heuristic labels
A few simple heuristics are fine:
- recent question/prompt marker in output → `waiting_input`
- no output for configured time while process alive → `idle`
- missing tmux/process unexpectedly → `lost`

### Example activity labels
- `Editing checkout totals`
- `Running test suite`
- `Waiting for approval`
- `Idle for 6m`
- `Exited with failure`

The heuristic layer must never override obvious deterministic truth.

---

## Event Model
Store lightweight timeline events.

Example event types:
- session created
- worktree created
- branch created
- tmux session started
- Codex launched
- Codex session id captured
- output detected
- status changed
- session opened
- session stopped
- process exited

Each event should contain:
- session id
- timestamp
- type
- short message
- optional metadata JSON

---

## Frontend Requirements
The frontend should be visibly inspired by the provided infra screenshots.

## Visual Direction
Use a dark, polished operations-dashboard aesthetic:
- deep blue / graphite tones
- subtle glow/border cards
- rounded corners
- strong spacing
- large heading
- readable typography
- charts in a lower section

## Main Views

### 1. Dashboard View
The default overview.

#### Top header
- title: `codex-session-manager`
- session selector or `All Sessions`
- refresh interval selector
- manual refresh button
- optional status filter

#### Snapshot banner
Examples:
- `Snapshot 14:20:18 [3 running · 1 waiting · 1 failed]`
- `Snapshot 14:20:18 [Selected: vat-fix · Running]`

#### Summary cards
At minimum:

##### Card: Target / Session
- session name
- target/repo label
- last updated time
- status badge
- mode badge

##### Card: Activity
- last known activity
- last output age
- active vs idle note
- source note like `derived from logs`

##### Card: Repo State
- repo/worktree
- branch
- changed files count
- clean/dirty state

##### Card: Execution
- profile
- approval policy
- tmux session
- pid/process health

##### Card: Validation
- latest test result
- latest lint result
- exit code if ended

### 2. Session Grid
A monitoring-board style view for many sessions.

Each session card should show:
- name
- status badge
- repo/target
- branch
- profile
- changed files count
- last activity
- updated time
- quick actions: inspect, open, stop

### 3. Session Detail View
A focused view for one selected session.

Should include:
- snapshot banner
- metadata cards
- prompt block
- recent output panel
- changed files panel
- event timeline
- lightweight charts

---

## Charts for V1
Keep charts simple and useful.

Recommended charts:
- output activity over time
- changed files count over time
- active vs idle timeline

If collecting time-series is too much for the first pass, structure the frontend so charts can initially use sampled snapshots.

---

## Suggested Project Structure
```text
codex-session-manager/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── cli/
│   │   ├── core/
│   │   ├── db/
│   │   ├── models/
│   │   ├── runners/
│   │   ├── services/
│   │   └── integrations/
│   ├── tests/
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   ├── hooks/
│   │   ├── lib/
│   │   └── types/
│   ├── public/
│   └── package.json
├── plans_v2.md
└── README.md
```

---

## Suggested Local Storage Layout
```text
~/.codexmgr/
  config.yaml
  codexmgr.db
  sessions/
    sess_001/
      output.log
      metadata.json
    sess_002/
      output.log
      metadata.json
```

---

## Phased Implementation Plan

## Phase 1 — Foundation
### Goal
Create the minimal backend and CLI skeleton.

### Deliverables
- SQLite schema
- session model
- event model
- Typer CLI skeleton
- core commands: start, list, inspect, stop
- tmux integration service shell

### Acceptance criteria
- a named session can be created
- it is stored in SQLite
- it appears in `list`
- `inspect` works
- `stop` updates state correctly

---

## Phase 2 — Runner + Worktrees
### Goal
Launch real managed Codex sessions safely.

### Deliverables
- worktree creation service
- branch naming strategy
- profile configuration
- Codex launch adapter
- log capture
- Codex session id capture if possible
- adopt flow

### Acceptance criteria
- writable sessions launch in their own worktree
- metadata is stored correctly
- adopted sessions can be registered

---

## Phase 3 — Monitoring
### Goal
Add reliable status tracking.

### Deliverables
- monitor loop/service
- process/tmux reconciliation
- last activity tracking
- changed files detection
- output tail retrieval
- deterministic state reconciliation rules

### Acceptance criteria
- running/stopped/failed/lost states are reliable
- changed file count updates
- recent output is visible
- idle/waiting heuristics work reasonably

---

## Phase 4 — Frontend Dashboard
### Goal
Build the first polished local UI.

### Deliverables
- dashboard page
- session grid/cards
- snapshot banner
- session detail view
- basic charts
- refresh control
- open/stop actions from UI

### Acceptance criteria
- dashboard clearly reflects session state
- detail view is usable for inspection
- layout follows the screenshot-inspired direction
- the UI feels like a real control plane, not a debug screen

---

## Phase 5 — Polish
### Goal
Make V1 pleasant enough for daily use.

### Deliverables
- Warp open integration
- improved status badges
- better event timeline
- archive/finished filters
- optional notifications for failed/waiting sessions
- config file support

### Acceptance criteria
- sessions can be reopened easily in Warp
- important states are visually obvious
- finished sessions remain inspectable

---

## Guidance for the Codex Window That Will Build This
The implementation should prioritize:
- correctness over cleverness
- deterministic monitoring over AI interpretation
- simple clean APIs
- a polished but practical dashboard
- strong local macOS ergonomics

### Recommended build order
1. backend models + SQLite
2. CLI commands
3. tmux runner
4. worktree support
5. monitoring loop
6. local API
7. frontend dashboard
8. Warp opener integration

### Important implementation decisions
- manager session id is canonical
- Codex session id is optional linked metadata
- writable sessions use separate worktrees by default
- frontend should stay clean and practical
- heuristics come after deterministic state works

---

## V1 Success Criteria
V1 is successful if:
- multiple Codex sessions can be started safely
- each session is trackable and inspectable
- sessions can be reopened quickly in Warp
- the dashboard makes it obvious what is happening
- the tool is stable enough for daily real work

---

## V2 Ideas
Not required now, but worth keeping in mind:
- local notifications
- small local model for summary text/classification only
- richer timelines and command history
- saved filters/views
- templates by repo type
- per-project test/lint adapters
- optional remote target support

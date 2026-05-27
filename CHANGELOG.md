# Changelog

## 2026-05-08

### Added
- Added a separate support log for Claude Code support feasibility, including provider-boundary guidance and initial implementation slices.
- Added opt-in browser desktop notifications for sessions that need attention, wait for input, fail, or become lost.
- Added a bounded automation sweep API that executes multiple high-priority follow-up actions while respecting queue duplicate suppression.
- Added dashboard support for running a capped automation sweep from the History automation queue.
- Added archive-handoff suppression so archive recommendations do not keep producing duplicate summaries after archive/stop handoffs exist.
- Added automation lineage fields on sessions so spawned follow-ups retain their parent session and automation action.
- Added duplicate suppression so active follow-up sessions prevent the queue from repeatedly spawning the same action for the same parent.
- Added dashboard visibility for automation parent/action metadata on spawned sessions.
- Added a global automation queue that ranks recommendations across sessions and exposes executable follow-up candidates.
- Added an execute-next automation API for starting the highest-priority safe follow-up session.
- Added dashboard automation queue controls in the History tab, including queue refresh, inspect, per-item execution, and execute-top.
- Added executable automation actions that convert recommendations into managed follow-up sessions for validation, review, investigation, recovery, and isolated continuation.
- Added an automation execution API for selected sessions, including generated handoff context and purpose-built follow-up prompts.
- Added dashboard support for starting follow-up sessions directly from automation recommendations.
- Added structured session handoffs with resume briefs, unresolved questions, validation state, files touched, next actions, notes, final disposition, and persisted automation recommendations.
- Added automation snapshots that turn session state into deterministic follow-up recommendations such as validation, review, unblock, recovery, archive, and overlap-comparison actions.
- Added searchable manager history with filters for repo, status, profile, validation state, and archived state, including latest handoff content in search results.
- Added history analytics for archived/active counts, needs-attention totals, validation failures, repeat abandoned work, and repo session patterns.
- Added repo session comparison for changed-file overlap across sessions.
- Added Codex environment management improvements for config presets, structured config editing, saved preset libraries, MCP dependency visibility, imported Codex history, and richer dashboard controls.

### Changed
- Updated the canonical plan to mark Layer 4 and Layer 5 as baseline implemented and Layer 8 notifications as partially implemented.
- Session stop now attempts to create a stop handoff automatically without blocking the stop operation if handoff generation fails.
- Dashboard detail loading now includes handoff history and automation recommendations for the selected session.
- Dashboard command panel now includes a History tab for search, analytics, handoff review, and repo comparison.

### Verified
- `backend/.venv/bin/pytest backend/tests -q`
- `npm run build`

# Changelog

## 2026-05-08

### Added
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
- Session stop now attempts to create a stop handoff automatically without blocking the stop operation if handoff generation fails.
- Dashboard detail loading now includes handoff history and automation recommendations for the selected session.
- Dashboard command panel now includes a History tab for search, analytics, handoff review, and repo comparison.

### Verified
- `backend/.venv/bin/pytest backend/tests -q`
- `npm run build`

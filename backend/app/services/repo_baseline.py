from __future__ import annotations

import json
from dataclasses import dataclass


def _parse_preview(raw_preview: str | None) -> list[str]:
    if not raw_preview:
        return []
    try:
        parsed = json.loads(raw_preview)
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed if item]


@dataclass(frozen=True, slots=True)
class RepoBaselineSnapshot:
    dirty_start_state: str
    dirty_start_reason: str | None
    changed_since_start: int
    changed_since_start_reason: str | None


def assess_repo_baseline(
    *,
    initial_changed_files_count: int,
    initial_changed_files_preview: str | None,
    changed_files_count: int,
    changed_files_preview: str | None,
) -> RepoBaselineSnapshot:
    dirty_start_state = "dirty" if initial_changed_files_count > 0 else "clean"
    dirty_start_reason = (
        f"repo started with {initial_changed_files_count} changed files"
        if initial_changed_files_count > 0
        else "repo started clean"
    )

    initial_preview = _parse_preview(initial_changed_files_preview)
    current_preview = _parse_preview(changed_files_preview)
    changed_since_start = int(
        changed_files_count != initial_changed_files_count
        or current_preview != initial_preview
    )
    changed_since_start_reason = None
    if changed_since_start:
        if dirty_start_state == "dirty":
            changed_since_start_reason = "repo started dirty and has diverged further since session start"
        elif changed_files_count > 0:
            changed_since_start_reason = "repo no longer matches the clean session start baseline"
        else:
            changed_since_start_reason = "repo state changed relative to the session start baseline"

    return RepoBaselineSnapshot(
        dirty_start_state=dirty_start_state,
        dirty_start_reason=dirty_start_reason,
        changed_since_start=changed_since_start,
        changed_since_start_reason=changed_since_start_reason,
    )

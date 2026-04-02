from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RepoRiskSnapshot:
    label: str
    reason: str
    overlap_paths: list[str]


def assess_repo_risk(
    *,
    mode: str,
    status: str,
    branch: str | None,
    worktree_path: str | None,
    changed_files_count: int,
    allow_write: int,
    active_repo_peers: int = 0,
    overlapping_paths: list[str] | None = None,
) -> RepoRiskSnapshot:
    normalized_branch = (branch or "").strip().lower()
    overlap_paths = sorted({path for path in (overlapping_paths or []) if path})
    if overlap_paths:
        preview = ", ".join(overlap_paths[:3])
        if len(overlap_paths) > 3:
            preview = f"{preview}, +{len(overlap_paths) - 3} more"
        if allow_write and not worktree_path:
            return RepoRiskSnapshot("high", f"multiple live sessions are changing the same files without isolation: {preview}", overlap_paths)
        return RepoRiskSnapshot("medium", f"multiple live sessions are changing the same files: {preview}", overlap_paths)

    if active_repo_peers > 0 and allow_write and not worktree_path:
        return RepoRiskSnapshot("high", "multiple live sessions share this repo without isolation", [])
    if active_repo_peers > 0:
        return RepoRiskSnapshot("medium", "multiple live sessions share this repo", [])
    if allow_write and changed_files_count > 0 and not worktree_path and normalized_branch in {"main", "master"}:
        return RepoRiskSnapshot("high", "writable changes on primary branch without isolation", [])
    if allow_write and not worktree_path and normalized_branch in {"main", "master"}:
        return RepoRiskSnapshot("high", "writable session on primary branch without isolation", [])
    if changed_files_count > 0 and not worktree_path and allow_write:
        return RepoRiskSnapshot("medium", "writable changes in repo root without worktree isolation", [])
    if mode == "adopted" and changed_files_count > 0:
        return RepoRiskSnapshot("medium", "adopted session is working in a changed repo", [])
    if status in {"finished", "stopped"}:
        return RepoRiskSnapshot("low", "inactive session", [])
    return RepoRiskSnapshot("low", "repo state looks normal", [])

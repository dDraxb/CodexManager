from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RepoPolicySnapshot:
    protected_branch_state: str
    protected_branch_reason: str | None
    isolation_state: str
    isolation_reason: str | None


PRIMARY_BRANCHES = {"main", "master"}


def assess_repo_policy(
    *,
    branch: str | None,
    allow_write: int,
    worktree_path: str | None,
    protected_branches: list[str] | None = None,
    require_worktree_for_write: bool = False,
) -> RepoPolicySnapshot:
    normalized_branch = (branch or "").strip().lower()
    writable = bool(allow_write)
    branch_set = {item.strip().lower() for item in (protected_branches or PRIMARY_BRANCHES) if item}
    on_primary = normalized_branch in (branch_set or PRIMARY_BRANCHES)
    isolated = bool(worktree_path)

    if writable and on_primary:
        protected_branch_state = "violation"
        protected_branch_reason = f"writable session is on protected branch {normalized_branch}"
    elif on_primary:
        protected_branch_state = "protected"
        protected_branch_reason = f"session is on protected branch {normalized_branch}"
    else:
        protected_branch_state = "clear"
        protected_branch_reason = None

    if not writable:
        isolation_state = "not_required"
        isolation_reason = "read-only session does not require worktree isolation"
    elif isolated:
        isolation_state = "satisfied"
        isolation_reason = "writable session is isolated in a dedicated worktree"
    elif require_worktree_for_write or on_primary:
        isolation_state = "required_missing"
        isolation_reason = "writable repo work should be isolated in a dedicated worktree"
    else:
        isolation_state = "recommended_missing"
        isolation_reason = "writable repo work is not isolated in a dedicated worktree"

    return RepoPolicySnapshot(
        protected_branch_state=protected_branch_state,
        protected_branch_reason=protected_branch_reason,
        isolation_state=isolation_state,
        isolation_reason=isolation_reason,
    )

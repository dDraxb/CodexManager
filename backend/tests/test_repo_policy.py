from __future__ import annotations


def test_assess_repo_policy_flags_writable_primary_branch_as_violation(configured_modules):
    from app.services.repo_policy import assess_repo_policy

    snapshot = assess_repo_policy(branch="main", allow_write=1, worktree_path=None)

    assert snapshot.protected_branch_state == "violation"
    assert snapshot.protected_branch_reason == "writable session is on protected branch main"
    assert snapshot.isolation_state == "required_missing"


def test_assess_repo_policy_marks_read_only_primary_branch_as_protected(configured_modules):
    from app.services.repo_policy import assess_repo_policy

    snapshot = assess_repo_policy(branch="master", allow_write=0, worktree_path=None)

    assert snapshot.protected_branch_state == "protected"
    assert snapshot.protected_branch_reason == "session is on protected branch master"
    assert snapshot.isolation_state == "not_required"


def test_assess_repo_policy_marks_isolated_writable_session_as_satisfied(configured_modules):
    from app.services.repo_policy import assess_repo_policy

    snapshot = assess_repo_policy(branch="feature/thing", allow_write=1, worktree_path="/tmp/worktree")

    assert snapshot.protected_branch_state == "clear"
    assert snapshot.isolation_state == "satisfied"
    assert snapshot.isolation_reason == "writable session is isolated in a dedicated worktree"

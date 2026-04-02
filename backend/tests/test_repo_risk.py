from __future__ import annotations


def test_assess_repo_risk_flags_writable_main_without_worktree_as_high(configured_modules):
    from app.services.repo_risk import assess_repo_risk

    snapshot = assess_repo_risk(
        mode="managed",
        status="running",
        branch="main",
        worktree_path=None,
        changed_files_count=2,
        allow_write=1,
        active_repo_peers=0,
    )

    assert snapshot.label == "high"


def test_assess_repo_risk_flags_adopted_dirty_repo_as_medium(configured_modules):
    from app.services.repo_risk import assess_repo_risk

    snapshot = assess_repo_risk(
        mode="adopted",
        status="idle",
        branch="feature/test",
        worktree_path=None,
        changed_files_count=1,
        allow_write=0,
        active_repo_peers=0,
    )

    assert snapshot.label == "medium"


def test_assess_repo_risk_marks_isolated_session_low(configured_modules):
    from app.services.repo_risk import assess_repo_risk

    snapshot = assess_repo_risk(
        mode="managed",
        status="running",
        branch="codex/task",
        worktree_path="/tmp/worktree",
        changed_files_count=3,
        allow_write=1,
        active_repo_peers=0,
    )

    assert snapshot.label == "low"


def test_assess_repo_risk_flags_multiple_live_writable_sessions_without_isolation(configured_modules):
    from app.services.repo_risk import assess_repo_risk

    snapshot = assess_repo_risk(
        mode="managed",
        status="running",
        branch="feature/test",
        worktree_path=None,
        changed_files_count=0,
        allow_write=1,
        active_repo_peers=1,
    )

    assert snapshot.label == "high"
    assert snapshot.reason == "multiple live sessions share this repo without isolation"


def test_assess_repo_risk_escalates_when_live_sessions_change_same_files(configured_modules):
    from app.services.repo_risk import assess_repo_risk

    snapshot = assess_repo_risk(
        mode="managed",
        status="running",
        branch="feature/test",
        worktree_path=None,
        changed_files_count=2,
        allow_write=1,
        active_repo_peers=1,
        overlapping_paths=["backend/app/api/server.py", "README.md"],
    )

    assert snapshot.label == "high"
    assert snapshot.reason == "multiple live sessions are changing the same files without isolation: README.md, backend/app/api/server.py"

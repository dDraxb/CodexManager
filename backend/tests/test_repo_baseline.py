from __future__ import annotations

import json


def test_assess_repo_baseline_marks_clean_start_without_drift(configured_modules):
    from app.services.repo_baseline import assess_repo_baseline

    snapshot = assess_repo_baseline(
        initial_changed_files_count=0,
        initial_changed_files_preview="[]",
        changed_files_count=0,
        changed_files_preview="[]",
    )

    assert snapshot.dirty_start_state == "clean"
    assert snapshot.changed_since_start == 0


def test_assess_repo_baseline_marks_dirty_start_and_further_drift(configured_modules):
    from app.services.repo_baseline import assess_repo_baseline

    snapshot = assess_repo_baseline(
        initial_changed_files_count=1,
        initial_changed_files_preview=json.dumps(["README.md"]),
        changed_files_count=2,
        changed_files_preview=json.dumps(["README.md", "backend/app/api/server.py"]),
    )

    assert snapshot.dirty_start_state == "dirty"
    assert snapshot.changed_since_start == 1
    assert snapshot.changed_since_start_reason == "repo started dirty and has diverged further since session start"

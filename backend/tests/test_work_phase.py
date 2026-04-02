from __future__ import annotations


def test_infer_work_phase_detects_planning(configured_modules):
    from app.services.work_phase import infer_work_phase

    snapshot = infer_work_phase(
        lines=["I’m treating this as a repo task and I’m going to inspect the codebase first."],
        session_status="running",
        changed_files_count=0,
        test_activity="none",
        test_status="unknown",
        lint_activity="none",
        lint_status="unknown",
        current_phase="unknown",
        current_confidence="low",
    )

    assert snapshot.phase == "planning"
    assert snapshot.confidence == "medium"
    assert snapshot.reason == "recent output looks like planning work; supported by the session is currently active"


def test_infer_work_phase_detects_editing(configured_modules):
    from app.services.work_phase import infer_work_phase

    snapshot = infer_work_phase(
        lines=["I updated backend/app/api/server.py and added the regression test."],
        session_status="running",
        changed_files_count=1,
        test_activity="none",
        test_status="unknown",
        lint_activity="none",
        lint_status="unknown",
        current_phase="planning",
        current_confidence="medium",
    )

    assert snapshot.phase == "editing"
    assert snapshot.confidence == "high"
    assert "file edits or implementation work" in snapshot.reason
    assert "the repo already has changed files" in snapshot.reason


def test_infer_work_phase_detects_reading(configured_modules):
    from app.services.work_phase import infer_work_phase

    snapshot = infer_work_phase(
        lines=["I’m reading the codebase and inspecting the implementation before editing anything."],
        session_status="running",
        changed_files_count=0,
        test_activity="none",
        test_status="unknown",
        lint_activity="none",
        lint_status="unknown",
        current_phase="planning",
        current_confidence="medium",
    )

    assert snapshot.phase == "reading"
    assert snapshot.confidence == "medium"
    assert snapshot.reason == "recent output looks like code reading or inspection; supported by the session is currently active"


def test_infer_work_phase_detects_reviewing(configured_modules):
    from app.services.work_phase import infer_work_phase

    snapshot = infer_work_phase(
        lines=["I’m verifying the final result and doing a sanity check before wrapping up."],
        session_status="running",
        changed_files_count=0,
        test_activity="none",
        test_status="unknown",
        lint_activity="none",
        lint_status="unknown",
        current_phase="editing",
        current_confidence="medium",
    )

    assert snapshot.phase == "reviewing"
    assert snapshot.confidence == "medium"
    assert snapshot.reason == "recent output looks like verification or review work; supported by the session is currently active"


def test_infer_work_phase_promotes_testing_confidence_with_result_evidence(configured_modules):
    from app.services.work_phase import infer_work_phase

    snapshot = infer_work_phase(
        lines=["Smoke test succeeded."],
        session_status="running",
        changed_files_count=0,
        test_activity="none",
        test_status="passed",
        lint_activity="none",
        lint_status="unknown",
        current_phase="reviewing",
        current_confidence="medium",
    )

    assert snapshot.phase == "testing"
    assert snapshot.confidence == "high"
    assert "validation or test work" in snapshot.reason
    assert "a recent validation result was observed" in snapshot.reason


def test_infer_work_phase_prefers_testing_when_validation_running(configured_modules):
    from app.services.work_phase import infer_work_phase

    snapshot = infer_work_phase(
        lines=["I updated backend/app/api/server.py and added the regression test."],
        session_status="running",
        changed_files_count=1,
        test_activity="active",
        test_status="unknown",
        lint_activity="none",
        lint_status="unknown",
        current_phase="editing",
        current_confidence="medium",
    )

    assert snapshot.phase == "testing"
    assert snapshot.confidence == "high"
    assert snapshot.reason == "validation activity is running now"


def test_infer_work_phase_respects_waiting_input_status(configured_modules):
    from app.services.work_phase import infer_work_phase

    snapshot = infer_work_phase(
        lines=[],
        session_status="waiting_input",
        changed_files_count=0,
        test_activity="none",
        test_status="unknown",
        lint_activity="none",
        lint_status="unknown",
        current_phase="editing",
        current_confidence="medium",
    )

    assert snapshot.phase == "waiting_input"
    assert snapshot.confidence == "high"
    assert snapshot.reason == "session status explicitly indicates it is waiting for approval or input"


def test_infer_work_phase_marks_finished_sessions_completed(configured_modules):
    from app.services.work_phase import infer_work_phase

    snapshot = infer_work_phase(
        lines=["Smoke test succeeded."],
        session_status="finished",
        changed_files_count=0,
        test_activity="none",
        test_status="passed",
        lint_activity="none",
        lint_status="unknown",
        current_phase="testing",
        current_confidence="high",
    )

    assert snapshot.phase == "completed"
    assert snapshot.confidence == "high"
    assert snapshot.reason == "session reached a terminal finished state"


def test_infer_work_phase_detects_blocked_with_high_confidence(configured_modules):
    from app.services.work_phase import infer_work_phase

    snapshot = infer_work_phase(
        lines=["Smoke test is blocked on missing environment variable and command not found errors."],
        session_status="running",
        changed_files_count=0,
        test_activity="none",
        test_status="unknown",
        lint_activity="none",
        lint_status="unknown",
        current_phase="testing",
        current_confidence="high",
    )

    assert snapshot.phase == "blocked"
    assert snapshot.confidence == "high"
    assert snapshot.reason == "recent output shows a blocking issue: missing environment configuration"
    assert snapshot.block_category == "environment"
    assert snapshot.block_reason == "missing environment configuration"


def test_infer_work_phase_classifies_blocked_categories(configured_modules):
    from app.services.work_phase import infer_work_phase

    snapshot = infer_work_phase(
        lines=["connection refused while contacting local service"],
        session_status="running",
        changed_files_count=0,
        test_activity="none",
        test_status="unknown",
        lint_activity="none",
        lint_status="unknown",
        current_phase="testing",
        current_confidence="high",
    )

    assert snapshot.phase == "blocked"
    assert snapshot.reason == "recent output shows a blocking issue: connection failure"
    assert snapshot.block_category == "network"
    assert snapshot.block_reason == "connection failure"


def test_infer_work_phase_preserves_existing_confidence_without_new_evidence(configured_modules):
    from app.services.work_phase import infer_work_phase

    snapshot = infer_work_phase(
        lines=[],
        session_status="idle",
        changed_files_count=3,
        test_activity="none",
        test_status="unknown",
        lint_activity="none",
        lint_status="unknown",
        current_phase="testing",
        current_confidence="high",
    )

    assert snapshot.phase == "testing"
    assert snapshot.confidence == "high"
    assert snapshot.block_reason is None
    assert snapshot.reason == "no stronger new evidence appeared, so the previous testing assessment is being preserved"


def test_infer_work_phase_uses_changed_files_to_promote_editing(configured_modules):
    from app.services.work_phase import infer_work_phase

    snapshot = infer_work_phase(
        lines=["I’m reading the codebase before making changes."],
        session_status="running",
        changed_files_count=4,
        test_activity="none",
        test_status="unknown",
        lint_activity="none",
        lint_status="unknown",
        current_phase="reading",
        current_confidence="medium",
    )

    assert snapshot.phase == "editing"
    assert snapshot.confidence == "high"
    assert snapshot.reason == "changed files appeared while the session remained active"

from __future__ import annotations


def test_analyze_validation_detects_pytest_success():
    from app.services.validation import ACTIVITY_NONE, STATUS_PASSED, STATUS_UNKNOWN, analyze_validation

    snapshot = analyze_validation(
        [
            "$ pytest",
            "============================== 12 passed in 0.42s ==============================",
        ]
    )

    assert snapshot.test_activity == ACTIVITY_NONE
    assert snapshot.test_status == STATUS_PASSED
    assert snapshot.lint_activity == ACTIVITY_NONE
    assert snapshot.lint_status == STATUS_UNKNOWN


def test_analyze_validation_detects_lint_failure():
    from app.services.validation import ACTIVITY_NONE, STATUS_FAILED, STATUS_UNKNOWN, analyze_validation

    snapshot = analyze_validation(
        [
            "$ ruff check .",
            "Would reformat: backend/app/api/server.py",
            "Found 1 error.",
        ]
    )

    assert snapshot.test_activity == ACTIVITY_NONE
    assert snapshot.test_status == STATUS_UNKNOWN
    assert snapshot.lint_activity == ACTIVITY_NONE
    assert snapshot.lint_status == STATUS_FAILED


def test_analyze_validation_detects_smoke_script_success():
    from app.services.validation import ACTIVITY_NONE, STATUS_PASSED, STATUS_UNKNOWN, analyze_validation

    snapshot = analyze_validation(
        [
            "• Ran ./bin/smoke_test.sh",
            "[2/6] Single mode start + status",
            "[6/6] PASS",
            "Smoke test succeeded.",
        ]
    )

    assert snapshot.test_activity == ACTIVITY_NONE
    assert snapshot.test_status == STATUS_PASSED
    assert snapshot.lint_activity == ACTIVITY_NONE
    assert snapshot.lint_status == STATUS_UNKNOWN


def test_analyze_validation_marks_running_activity_without_result():
    from app.services.validation import ACTIVITY_ACTIVE, STATUS_UNKNOWN, analyze_validation

    snapshot = analyze_validation(
        [
            "$ pytest",
            "collecting ...",
        ]
    )

    assert snapshot.test_activity == ACTIVITY_ACTIVE
    assert snapshot.test_status == STATUS_UNKNOWN


def test_analyze_validation_keeps_result_separate_from_new_command():
    from app.services.validation import ACTIVITY_ACTIVE, STATUS_PASSED, analyze_validation

    snapshot = analyze_validation(
        [
            "$ pytest",
            "============================== 4 passed in 0.20s ==============================",
            "$ pytest",
            "collecting ...",
        ]
    )

    assert snapshot.test_activity == ACTIVITY_ACTIVE
    assert snapshot.test_status == STATUS_PASSED


def test_analyze_validation_does_not_treat_smoke_test_prose_as_running():
    from app.services.validation import ACTIVITY_NONE, STATUS_UNKNOWN, analyze_validation

    snapshot = analyze_validation(
        [
            "Smoke test is blocked on missing environment variable",
            "I will verify the smoke test again after fixing the config.",
        ]
    )

    assert snapshot.test_activity == ACTIVITY_NONE
    assert snapshot.test_status == STATUS_UNKNOWN
    assert snapshot.lint_activity == ACTIVITY_NONE
    assert snapshot.lint_status == STATUS_UNKNOWN


def test_analyze_validation_does_not_treat_failure_prose_as_test_failure():
    from app.services.validation import ACTIVITY_NONE, STATUS_UNKNOWN, analyze_validation

    snapshot = analyze_validation(
        [
            "I’m running the full smoke test and will report the result plus any failures if it breaks.",
            "The smoke test is in progress.",
        ]
    )

    assert snapshot.test_activity == ACTIVITY_NONE
    assert snapshot.test_status == STATUS_UNKNOWN

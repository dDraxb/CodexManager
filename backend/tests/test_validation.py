from __future__ import annotations


def test_analyze_validation_detects_pytest_success():
    from app.services.validation import STATUS_PASSED, STATUS_UNKNOWN, analyze_validation

    snapshot = analyze_validation(
        [
            "$ pytest",
            "============================== 12 passed in 0.42s ==============================",
        ]
    )

    assert snapshot.test_status == STATUS_PASSED
    assert snapshot.lint_status == STATUS_UNKNOWN


def test_analyze_validation_detects_lint_failure():
    from app.services.validation import STATUS_FAILED, STATUS_UNKNOWN, analyze_validation

    snapshot = analyze_validation(
        [
            "$ ruff check .",
            "Would reformat: backend/app/api/server.py",
            "Found 1 error.",
        ]
    )

    assert snapshot.test_status == STATUS_UNKNOWN
    assert snapshot.lint_status == STATUS_FAILED


def test_analyze_validation_detects_smoke_script_success():
    from app.services.validation import STATUS_PASSED, STATUS_UNKNOWN, analyze_validation

    snapshot = analyze_validation(
        [
            "• Ran ./bin/smoke_test.sh",
            "[2/6] Single mode start + status",
            "[6/6] PASS",
            "Smoke test succeeded.",
        ]
    )

    assert snapshot.test_status == STATUS_PASSED
    assert snapshot.lint_status == STATUS_UNKNOWN

from __future__ import annotations


def test_completion_state_reports_in_progress_for_live_sessions(configured_modules):
    from app.services.completion_state import assess_completion_state

    snapshot = assess_completion_state(
        status="running",
        review_readiness_state="ready",
        review_readiness_reason="required validation checks are satisfied",
    )

    assert snapshot.state == "in_progress"
    assert snapshot.reason == "the session is still actively in progress"


def test_completion_state_keeps_not_ready_for_live_sessions_when_review_is_blocked(configured_modules):
    from app.services.completion_state import assess_completion_state

    snapshot = assess_completion_state(
        status="running",
        review_readiness_state="not_ready",
        review_readiness_reason="required validation checks are still missing",
    )

    assert snapshot.state == "not_ready"
    assert snapshot.reason == "required validation checks are still missing"


def test_completion_state_reports_ready_for_review(configured_modules):
    from app.services.completion_state import assess_completion_state

    snapshot = assess_completion_state(
        status="idle",
        review_readiness_state="ready",
        review_readiness_reason="required validation checks are satisfied",
    )

    assert snapshot.state == "ready_for_review"
    assert snapshot.reason == "required validation checks are satisfied"


def test_completion_state_reports_ready_with_gaps(configured_modules):
    from app.services.completion_state import assess_completion_state

    snapshot = assess_completion_state(
        status="idle",
        review_readiness_state="ready_with_gaps",
        review_readiness_reason="only optional validation checks are still pending",
    )

    assert snapshot.state == "ready_with_gaps"
    assert snapshot.reason == "only optional validation checks are still pending"


def test_completion_state_reports_not_ready(configured_modules):
    from app.services.completion_state import assess_completion_state

    snapshot = assess_completion_state(
        status="idle",
        review_readiness_state="not_ready",
        review_readiness_reason="required validation checks are still missing",
    )

    assert snapshot.state == "not_ready"
    assert snapshot.reason == "required validation checks are still missing"

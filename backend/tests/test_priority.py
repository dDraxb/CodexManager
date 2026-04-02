from __future__ import annotations


def test_assess_session_priority_elevates_blocked_sessions(configured_modules):
    from app.services.priority import assess_session_priority

    snapshot = assess_session_priority(
        status="running",
        work_phase="blocked",
        block_category="tooling",
        block_reason="command not found",
        repo_risk_label="low",
        repo_risk_reason="repo state looks normal",
        health_label="attention",
        test_status="unknown",
        lint_status="unknown",
        attachment_state="attached",
        idle_age_seconds=10,
        needs_attention=0,
        idle_threshold_seconds=300,
    )

    assert snapshot.score >= 95
    assert snapshot.reason == "command not found"
    assert snapshot.evidence == "the session is blocked in tooling flow"


def test_assess_session_priority_elevates_multi_session_repo_conflict(configured_modules):
    from app.services.priority import assess_session_priority

    snapshot = assess_session_priority(
        status="running",
        work_phase="editing",
        block_category=None,
        block_reason=None,
        repo_risk_label="high",
        repo_risk_reason="multiple live sessions share this repo without isolation",
        health_label="attention",
        test_status="unknown",
        lint_status="unknown",
        attachment_state="attached",
        idle_age_seconds=10,
        needs_attention=0,
        idle_threshold_seconds=300,
    )

    assert snapshot.score >= 89
    assert snapshot.reason == "multiple live sessions share this repo without isolation"
    assert snapshot.evidence == "repo risk detection found a high-risk execution context"


def test_assess_session_priority_labels_approval_block_clearly(configured_modules):
    from app.services.priority import assess_session_priority

    snapshot = assess_session_priority(
        status="running",
        work_phase="blocked",
        block_category="approval",
        block_reason="awaiting approval",
        repo_risk_label="low",
        repo_risk_reason="repo state looks normal",
        health_label="attention",
        test_status="unknown",
        lint_status="unknown",
        attachment_state="attached",
        idle_age_seconds=10,
        needs_attention=0,
        idle_threshold_seconds=300,
    )

    assert snapshot.score >= 90
    assert snapshot.reason == "approval needed"
    assert snapshot.evidence == "the session is blocked in approval flow"


def test_assess_session_priority_elevates_waiting_input_sessions(configured_modules):
    from app.services.priority import assess_session_priority

    snapshot = assess_session_priority(
        status="waiting_input",
        work_phase="waiting_input",
        block_category="input",
        block_reason="awaiting approval or input",
        repo_risk_label="low",
        repo_risk_reason="repo state looks normal",
        health_label="attention",
        test_status="unknown",
        lint_status="unknown",
        attachment_state="attached",
        idle_age_seconds=10,
        needs_attention=0,
        idle_threshold_seconds=300,
    )

    assert snapshot.score >= 90
    assert snapshot.reason == "waiting for user input"
    assert snapshot.evidence == "the live session is waiting on an external response"

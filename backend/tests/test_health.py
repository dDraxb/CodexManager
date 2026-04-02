from __future__ import annotations


def test_assess_session_health_marks_running_attached_session_healthy(configured_modules):
    from app.services.health import assess_session_health

    snapshot = assess_session_health(
        status="running",
        work_phase="editing",
        block_category=None,
        block_reason=None,
        repo_risk_label="low",
        repo_risk_reason="repo state looks normal",
        test_status="unknown",
        lint_status="unknown",
        attachment_state="attached",
        idle_age_seconds=12,
        needs_attention=0,
        idle_threshold_seconds=300,
    )

    assert snapshot.label == "healthy"
    assert snapshot.score >= 80
    assert snapshot.evidence == "no elevated risk signals are active"


def test_assess_session_health_surfaces_multi_session_repo_conflict(configured_modules):
    from app.services.health import assess_session_health

    snapshot = assess_session_health(
        status="running",
        work_phase="editing",
        block_category=None,
        block_reason=None,
        repo_risk_label="high",
        repo_risk_reason="multiple live sessions share this repo without isolation",
        test_status="unknown",
        lint_status="unknown",
        attachment_state="attached",
        idle_age_seconds=12,
        needs_attention=0,
        idle_threshold_seconds=300,
    )

    assert snapshot.label == "attention"
    assert snapshot.reason == "multiple live sessions share this repo without isolation"
    assert snapshot.evidence == "repo risk detection found a high-risk execution context"


def test_assess_session_health_marks_blocked_session_attention(configured_modules):
    from app.services.health import assess_session_health

    snapshot = assess_session_health(
        status="running",
        work_phase="blocked",
        block_category="tooling",
        block_reason="command not found",
        repo_risk_label="low",
        repo_risk_reason="repo state looks normal",
        test_status="unknown",
        lint_status="unknown",
        attachment_state="attached",
        idle_age_seconds=20,
        needs_attention=0,
        idle_threshold_seconds=300,
    )

    assert snapshot.label == "attention"
    assert snapshot.reason == "command not found"
    assert snapshot.evidence == "the session is blocked in tooling flow"


def test_assess_session_health_distinguishes_approval_block(configured_modules):
    from app.services.health import assess_session_health

    snapshot = assess_session_health(
        status="running",
        work_phase="blocked",
        block_category="approval",
        block_reason="awaiting approval",
        repo_risk_label="low",
        repo_risk_reason="repo state looks normal",
        test_status="unknown",
        lint_status="unknown",
        attachment_state="attached",
        idle_age_seconds=20,
        needs_attention=0,
        idle_threshold_seconds=300,
    )

    assert snapshot.label == "attention"
    assert snapshot.reason == "waiting for approval"
    assert snapshot.evidence == "the session is blocked in approval flow"


def test_assess_session_health_marks_long_idle_detached_session_monitor(configured_modules):
    from app.services.health import assess_session_health

    snapshot = assess_session_health(
        status="idle",
        work_phase="testing",
        block_category=None,
        block_reason=None,
        repo_risk_label="low",
        repo_risk_reason="repo state looks normal",
        test_status="unknown",
        lint_status="unknown",
        attachment_state="detached",
        idle_age_seconds=900,
        needs_attention=0,
        idle_threshold_seconds=300,
    )

    assert snapshot.label == "monitor"
    assert snapshot.reason == "idle for a long time"
    assert snapshot.evidence == "idle age exceeded twice the monitoring threshold"

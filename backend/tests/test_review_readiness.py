from __future__ import annotations


def test_review_readiness_ready_when_required_checks_are_satisfied(configured_modules):
    from app.services.review_readiness import assess_review_readiness

    snapshot = assess_review_readiness(
        status="idle",
        validation_policy_state="ready",
        changed_since_green_validation=0,
        repo_risk_label="low",
        repo_risk_reason="repo state looks normal",
        block_reason=None,
    )

    assert snapshot.state == "ready"
    assert snapshot.reason == "required validation checks are satisfied"


def test_review_readiness_ready_with_gaps_when_only_optional_checks_remain(configured_modules):
    from app.services.review_readiness import assess_review_readiness

    snapshot = assess_review_readiness(
        status="idle",
        validation_policy_state="optional_pending",
        changed_since_green_validation=0,
        repo_risk_label="low",
        repo_risk_reason="repo state looks normal",
        block_reason=None,
    )

    assert snapshot.state == "ready_with_gaps"
    assert snapshot.reason == "only optional validation checks are still pending"


def test_review_readiness_not_ready_when_required_checks_are_missing(configured_modules):
    from app.services.review_readiness import assess_review_readiness

    snapshot = assess_review_readiness(
        status="idle",
        validation_policy_state="required_missing",
        changed_since_green_validation=0,
        repo_risk_label="low",
        repo_risk_reason="repo state looks normal",
        block_reason=None,
    )

    assert snapshot.state == "not_ready"
    assert snapshot.reason == "required validation checks are still missing"


def test_review_readiness_not_ready_when_code_changed_since_green(configured_modules):
    from app.services.review_readiness import assess_review_readiness

    snapshot = assess_review_readiness(
        status="idle",
        validation_policy_state="ready",
        changed_since_green_validation=1,
        repo_risk_label="low",
        repo_risk_reason="repo state looks normal",
        block_reason=None,
    )

    assert snapshot.state == "not_ready"
    assert snapshot.reason == "code changed since the last green validation"

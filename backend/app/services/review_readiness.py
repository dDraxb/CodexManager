from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReviewReadinessSnapshot:
    state: str
    reason: str


def assess_review_readiness(
    *,
    status: str,
    validation_policy_state: str,
    changed_since_green_validation: int,
    repo_risk_label: str,
    repo_risk_reason: str,
    block_reason: str | None,
) -> ReviewReadinessSnapshot:
    if status in {"failed", "lost"}:
        return ReviewReadinessSnapshot("not_ready", f"session is {status}")
    if block_reason:
        return ReviewReadinessSnapshot("not_ready", block_reason)
    if repo_risk_label == "high":
        return ReviewReadinessSnapshot("not_ready", repo_risk_reason)
    if changed_since_green_validation:
        return ReviewReadinessSnapshot("not_ready", "code changed since the last green validation")
    if validation_policy_state == "required_missing":
        return ReviewReadinessSnapshot("not_ready", "required validation checks are still missing")
    if validation_policy_state == "optional_pending":
        return ReviewReadinessSnapshot("ready_with_gaps", "only optional validation checks are still pending")
    if validation_policy_state == "ready":
        return ReviewReadinessSnapshot("ready", "required validation checks are satisfied")
    return ReviewReadinessSnapshot("unknown", "review readiness has not been established yet")

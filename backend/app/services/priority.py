from __future__ import annotations

from dataclasses import dataclass

from app.models.session import SessionStatus
from app.services.validation import STATUS_FAILED
from app.services.work_phase import (
    BLOCK_CATEGORY_APPROVAL,
    BLOCK_CATEGORY_DEPENDENCY,
    BLOCK_CATEGORY_ENVIRONMENT,
    BLOCK_CATEGORY_FILESYSTEM,
    BLOCK_CATEGORY_INPUT,
    BLOCK_CATEGORY_NETWORK,
    BLOCK_CATEGORY_TOOLING,
    PHASE_BLOCKED,
)


@dataclass(frozen=True, slots=True)
class PrioritySnapshot:
    score: int
    reason: str
    evidence: str


def _blocked_priority_reason(block_category: str | None, block_reason: str | None) -> tuple[int, str]:
    if block_category == BLOCK_CATEGORY_APPROVAL:
        return 93, "approval needed"
    if block_category == BLOCK_CATEGORY_INPUT:
        return 92, "waiting for user input"
    if block_category == BLOCK_CATEGORY_ENVIRONMENT:
        return 95, block_reason or "environment needs configuration"
    if block_category == BLOCK_CATEGORY_DEPENDENCY:
        return 95, block_reason or "dependency issue"
    if block_category == BLOCK_CATEGORY_NETWORK:
        return 96, block_reason or "network or service failure"
    if block_category == BLOCK_CATEGORY_FILESYSTEM:
        return 96, block_reason or "filesystem access problem"
    if block_category == BLOCK_CATEGORY_TOOLING:
        return 95, block_reason or "tooling problem"
    return 95, block_reason or "session is blocked"


def assess_session_priority(
    *,
    status: str,
    work_phase: str | None,
    block_category: str | None,
    block_reason: str | None,
    repo_risk_label: str,
    repo_risk_reason: str,
    health_label: str,
    test_status: str | None,
    lint_status: str | None,
    attachment_state: str | None,
    idle_age_seconds: int | None,
    needs_attention: int,
    idle_threshold_seconds: int,
) -> PrioritySnapshot:
    score = 10
    reason = "stable background session"
    evidence = "no urgent intervention signals are active"

    if status in {SessionStatus.FAILED.value, SessionStatus.LOST.value}:
        return PrioritySnapshot(98, f"session {status}", "the session is in a terminal failure state")
    if work_phase == PHASE_BLOCKED:
        score, reason = _blocked_priority_reason(block_category, block_reason)
        return PrioritySnapshot(score, reason, f"the session is blocked in {block_category or 'an unknown'} flow")
    if repo_risk_label == "high":
        return PrioritySnapshot(89, repo_risk_reason, "repo risk detection found a high-risk execution context")
    if repo_risk_label == "medium":
        return PrioritySnapshot(72, repo_risk_reason, "repo risk detection found a medium-risk execution context")
    if status == SessionStatus.WAITING_INPUT.value:
        return PrioritySnapshot(92, "waiting for user input", "the live session is waiting on an external response")
    if test_status == STATUS_FAILED or lint_status == STATUS_FAILED:
        return PrioritySnapshot(90, "validation failed", "the latest observed validation result is failed")
    if needs_attention:
        return PrioritySnapshot(88, "marked as needing attention", "validation or monitoring explicitly marked the session")
    if status == SessionStatus.RUNNING.value and attachment_state == "detached":
        return PrioritySnapshot(76, "active without attached terminal", "the session is active but no terminal is attached")
    if status == SessionStatus.RUNNING.value:
        return PrioritySnapshot(68, "currently active", "the session is actively producing work")
    if status == SessionStatus.IDLE.value and idle_age_seconds is not None and idle_age_seconds >= idle_threshold_seconds * 2:
        return PrioritySnapshot(58, "stale idle session", "idle age exceeded twice the monitoring threshold")
    if health_label == "monitor":
        return PrioritySnapshot(52, "worth monitoring", "health assessment says the session should be monitored")
    if status in {SessionStatus.CREATED.value, SessionStatus.STARTING.value}:
        return PrioritySnapshot(46, "starting up", "the session is still in startup flow")
    if status in {SessionStatus.FINISHED.value, SessionStatus.STOPPED.value}:
        return PrioritySnapshot(8, "inactive by design", "the session is in an expected inactive terminal state")
    return PrioritySnapshot(score, reason, evidence)

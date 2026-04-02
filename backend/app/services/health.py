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
class HealthSnapshot:
    score: int
    label: str
    reason: str
    evidence: str


def _blocked_health_reason(block_category: str | None, block_reason: str | None) -> tuple[int, str]:
    if block_category == BLOCK_CATEGORY_APPROVAL:
        return 41, "waiting for approval"
    if block_category == BLOCK_CATEGORY_INPUT:
        return 43, "waiting for user input"
    if block_category == BLOCK_CATEGORY_ENVIRONMENT:
        return 28, block_reason or "environment needs configuration"
    if block_category == BLOCK_CATEGORY_DEPENDENCY:
        return 28, block_reason or "dependency issue"
    if block_category == BLOCK_CATEGORY_NETWORK:
        return 26, block_reason or "network or service failure"
    if block_category == BLOCK_CATEGORY_FILESYSTEM:
        return 24, block_reason or "filesystem access problem"
    if block_category == BLOCK_CATEGORY_TOOLING:
        return 24, block_reason or "tooling problem"
    return 30, block_reason or "session is blocked"


def _label_for_score(score: int) -> str:
    if score >= 80:
        return "healthy"
    if score >= 50:
        return "monitor"
    return "attention"


def assess_session_health(
    *,
    status: str,
    work_phase: str | None,
    block_category: str | None,
    block_reason: str | None,
    repo_risk_label: str,
    repo_risk_reason: str,
    test_status: str | None,
    lint_status: str | None,
    attachment_state: str | None,
    idle_age_seconds: int | None,
    needs_attention: int,
    idle_threshold_seconds: int,
) -> HealthSnapshot:
    score = 90
    reason = "session looks healthy"
    evidence = "no elevated risk signals are active"

    if status in {SessionStatus.FAILED.value, SessionStatus.LOST.value}:
        score = 15
        reason = f"session {status}"
        evidence = "the session is in a terminal failure state"
    elif test_status == STATUS_FAILED or lint_status == STATUS_FAILED:
        score = 35
        reason = "validation failed"
        evidence = "the latest observed validation result is failed"
    elif work_phase == PHASE_BLOCKED:
        score, reason = _blocked_health_reason(block_category, block_reason)
        evidence = f"the session is blocked in {block_category or 'an unknown'} flow"
    elif repo_risk_label == "high":
        score = 42
        reason = repo_risk_reason
        evidence = "repo risk detection found a high-risk execution context"
    elif repo_risk_label == "medium":
        score = 58
        reason = repo_risk_reason
        evidence = "repo risk detection found a medium-risk execution context"
    elif status == SessionStatus.WAITING_INPUT.value:
        score = 45
        reason = "awaiting user input"
        evidence = "the live session is waiting on an external response"
    elif status == SessionStatus.IDLE.value and idle_age_seconds is not None and idle_age_seconds >= idle_threshold_seconds * 2:
        score = 55
        reason = "idle for a long time"
        evidence = "idle age exceeded twice the monitoring threshold"
    elif status == SessionStatus.IDLE.value and attachment_state == "detached":
        score = 62
        reason = "idle and detached"
        evidence = "the session is idle and no terminal is attached"
    elif status == SessionStatus.RUNNING.value and attachment_state == "detached":
        score = 72
        reason = "running without attached terminal"
        evidence = "the session is active but currently detached"
    elif status in {SessionStatus.CREATED.value, SessionStatus.STARTING.value}:
        score = 82
        reason = "session is starting"
        evidence = "the session is still in startup flow"
    elif status in {SessionStatus.FINISHED.value, SessionStatus.STOPPED.value}:
        score = 84
        reason = "inactive by design"
        evidence = "the session is in an expected inactive terminal state"

    if needs_attention and score > 49:
        score = 49
        reason = reason if reason != "session looks healthy" else "needs attention"
        evidence = f"{evidence}; validation or monitoring marked this session for attention"

    return HealthSnapshot(score=score, label=_label_for_score(score), reason=reason, evidence=evidence)

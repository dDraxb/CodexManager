from __future__ import annotations

from dataclasses import dataclass


IN_PROGRESS_STATUSES = {"created", "starting", "running", "waiting_input"}


@dataclass(frozen=True, slots=True)
class CompletionStateSnapshot:
    state: str
    reason: str


def assess_completion_state(
    *,
    status: str,
    review_readiness_state: str,
    review_readiness_reason: str | None,
) -> CompletionStateSnapshot:
    if review_readiness_state == "not_ready":
        return CompletionStateSnapshot("not_ready", review_readiness_reason or "the session is not ready for review yet")
    if status in IN_PROGRESS_STATUSES:
        return CompletionStateSnapshot("in_progress", "the session is still actively in progress")
    if review_readiness_state == "ready":
        return CompletionStateSnapshot("ready_for_review", review_readiness_reason or "the session is ready for review")
    if review_readiness_state == "ready_with_gaps":
        return CompletionStateSnapshot("ready_with_gaps", review_readiness_reason or "only optional validation gaps remain")
    return CompletionStateSnapshot("unknown", "completion state has not been established yet")

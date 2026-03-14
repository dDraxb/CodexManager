from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class SessionMode(StrEnum):
    MANAGED = "managed"
    ADOPTED = "adopted"


class SessionStatus(StrEnum):
    CREATED = "created"
    STARTING = "starting"
    RUNNING = "running"
    WAITING_INPUT = "waiting_input"
    IDLE = "idle"
    FINISHED = "finished"
    FAILED = "failed"
    STOPPED = "stopped"
    LOST = "lost"


TERMINAL_STATUSES = {
    SessionStatus.FINISHED.value,
    SessionStatus.FAILED.value,
    SessionStatus.STOPPED.value,
}

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    SessionStatus.CREATED.value: {
        SessionStatus.STARTING.value,
        SessionStatus.RUNNING.value,
        SessionStatus.FAILED.value,
        SessionStatus.STOPPED.value,
        SessionStatus.LOST.value,
    },
    SessionStatus.STARTING.value: {
        SessionStatus.RUNNING.value,
        SessionStatus.WAITING_INPUT.value,
        SessionStatus.IDLE.value,
        SessionStatus.FAILED.value,
        SessionStatus.LOST.value,
        SessionStatus.STOPPED.value,
    },
    SessionStatus.RUNNING.value: {
        SessionStatus.WAITING_INPUT.value,
        SessionStatus.IDLE.value,
        SessionStatus.FINISHED.value,
        SessionStatus.FAILED.value,
        SessionStatus.STOPPED.value,
        SessionStatus.LOST.value,
    },
    SessionStatus.WAITING_INPUT.value: {
        SessionStatus.RUNNING.value,
        SessionStatus.IDLE.value,
        SessionStatus.FINISHED.value,
        SessionStatus.FAILED.value,
        SessionStatus.STOPPED.value,
        SessionStatus.LOST.value,
    },
    SessionStatus.IDLE.value: {
        SessionStatus.RUNNING.value,
        SessionStatus.WAITING_INPUT.value,
        SessionStatus.FINISHED.value,
        SessionStatus.FAILED.value,
        SessionStatus.STOPPED.value,
        SessionStatus.LOST.value,
    },
    SessionStatus.FINISHED.value: set(),
    SessionStatus.FAILED.value: set(),
    SessionStatus.STOPPED.value: set(),
    SessionStatus.LOST.value: {
        SessionStatus.RUNNING.value,
        SessionStatus.STOPPED.value,
        SessionStatus.FAILED.value,
    },
}


@dataclass(slots=True)
class SessionRecord:
    id: str
    name: str
    mode: str
    status: str
    codex_session_id: str | None
    repo_path: str
    worktree_path: str | None
    branch: str | None
    profile: str
    approval_policy: str | None
    allow_write: int
    allow_shell: int
    tmux_session: str | None
    pid: int | None
    prompt: str | None
    created_at: str
    started_at: str | None
    finished_at: str | None
    last_activity_at: str | None
    last_known_activity: str | None
    changed_files_count: int
    changed_files_preview: str
    test_status: str | None
    lint_status: str | None
    exit_code: int | None
    log_path: str
    cwd: str | None
    target_label: str | None
    observability: str
    needs_attention: int
    require_changelog: int
    attachment_state: str | None
    last_attached_at: str | None
    last_detached_at: str | None
    output_fingerprint: str | None
    output_observed_at: str | None
    updated_at: str

    @classmethod
    def from_row(cls, row: Any) -> "SessionRecord":
        return cls(**dict(row))

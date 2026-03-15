from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from app.core.settings import load_settings
from app.db.database import get_conn
from app.models.session import SessionStatus
from app.runner.client import get_runner_client
from app.runner.contracts import RunnerClient, RunnerError
from app.services.sessions import _event, list_sessions, refresh_git_state, update_status
from app.services.validation import STATUS_FAILED, analyze_validation

ATTACH_ACTIVITY_GRACE_SECONDS = 15



def _file_age_seconds(path: str) -> int | None:
    p = Path(path)
    if not p.exists():
        return None
    mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=UTC)
    return int((datetime.now(UTC) - mtime).total_seconds())


def _iso_age_seconds(timestamp: str | None) -> int | None:
    if not timestamp:
        return None
    try:
        observed = datetime.fromisoformat(timestamp)
    except ValueError:
        return None
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=UTC)
    return int((datetime.now(UTC) - observed).total_seconds())


def _pane_fingerprint(lines: list[str]) -> str | None:
    if not lines:
        return None
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def _min_age(current_age: int | None, candidate_age: int | None) -> int | None:
    if current_age is None:
        return candidate_age
    if candidate_age is None:
        return current_age
    return min(current_age, candidate_age)


def _record_output_observation(session_id: str, fingerprint: str, observed_at: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE sessions SET output_fingerprint = ?, output_observed_at = ?, updated_at = ? WHERE id = ?",
            (fingerprint, observed_at, observed_at, session_id),
        )


def _record_output_fingerprint(session_id: str, fingerprint: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE sessions SET output_fingerprint = ?, updated_at = ? WHERE id = ?",
            (fingerprint, datetime.now(UTC).replace(microsecond=0).isoformat(), session_id),
        )


def _record_attachment_state(session_id: str, attachment_state: str, timestamp: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE sessions
            SET attachment_state = ?, last_attached_at = CASE WHEN ? = 'attached' THEN ? ELSE last_attached_at END,
                last_detached_at = CASE WHEN ? = 'detached' THEN ? ELSE last_detached_at END,
                updated_at = ?
            WHERE id = ?
            """,
            (attachment_state, attachment_state, timestamp, attachment_state, timestamp, timestamp, session_id),
        )


def _record_validation_state(session_id: str, *, test_status: str, lint_status: str, needs_attention: bool) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE sessions
            SET test_status = ?, lint_status = ?, needs_attention = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                test_status,
                lint_status,
                1 if needs_attention else 0,
                datetime.now(UTC).replace(microsecond=0).isoformat(),
                session_id,
            ),
        )


def _session_needs_attention(session_status: str, *, test_status: str, lint_status: str) -> bool:
    if session_status in {SessionStatus.FAILED.value, SessionStatus.LOST.value, SessionStatus.WAITING_INPUT.value}:
        return True
    return test_status == STATUS_FAILED or lint_status == STATUS_FAILED


def _refresh_validation_state(session, lines: list[str]) -> None:
    snapshot = analyze_validation(lines)
    if snapshot.test_status == session.test_status and snapshot.lint_status == session.lint_status:
        return

    needs_attention = _session_needs_attention(
        session.status,
        test_status=snapshot.test_status,
        lint_status=snapshot.lint_status,
    )
    _record_validation_state(
        session.id,
        test_status=snapshot.test_status,
        lint_status=snapshot.lint_status,
        needs_attention=needs_attention,
    )
    if snapshot.test_status != session.test_status:
        _event(
            session.id,
            "validation_changed",
            f"Tests {snapshot.test_status}",
            {"kind": "tests", "status": snapshot.test_status},
        )
        session.test_status = snapshot.test_status
    if snapshot.lint_status != session.lint_status:
        _event(
            session.id,
            "validation_changed",
            f"Lint {snapshot.lint_status}",
            {"kind": "lint", "status": snapshot.lint_status},
        )
        session.lint_status = snapshot.lint_status
    session.needs_attention = 1 if needs_attention else 0



def reconcile_once(runner: RunnerClient | None = None) -> int:
    settings = load_settings()
    client = runner or get_runner_client()
    touched = 0
    for session in list_sessions():
        session = refresh_git_state(session, runner=client)
        attachment_changed = False

        if session.status in {SessionStatus.FINISHED.value, SessionStatus.FAILED.value, SessionStatus.STOPPED.value}:
            continue

        tmux_ok = bool(session.tmux_session and client.session_exists(session.tmux_session))
        if not tmux_ok and session.mode == "managed":
            if (session.attachment_state or "detached") != "detached":
                timestamp = datetime.now(UTC).replace(microsecond=0).isoformat()
                _record_attachment_state(session.id, "detached", timestamp)
                _event(
                    session.id,
                    "attachment_changed",
                    "Session detached",
                    {"attachment_state": "detached"},
                )
                session.attachment_state = "detached"
                session.last_detached_at = timestamp
            if session.status != SessionStatus.LOST.value:
                update_status(session.id, SessionStatus.LOST, "tmux session missing")
                touched += 1
            continue

        if tmux_ok and session.tmux_session:
            try:
                attachment_state = "attached" if client.is_session_attached(session.tmux_session) else "detached"
            except RunnerError:
                attachment_state = session.attachment_state or "detached"
            else:
                if attachment_state != (session.attachment_state or "detached"):
                    timestamp = datetime.now(UTC).replace(microsecond=0).isoformat()
                    _record_attachment_state(session.id, attachment_state, timestamp)
                    _event(
                        session.id,
                        "attachment_changed",
                        f"Session {attachment_state}",
                        {"attachment_state": attachment_state},
                    )
                    session.attachment_state = attachment_state
                    attachment_changed = True
                    if attachment_state == "attached":
                        session.last_attached_at = timestamp
                    else:
                        session.last_detached_at = timestamp

        idle_age = _file_age_seconds(session.log_path)
        lines: list[str] = []
        if tmux_ok and session.tmux_session:
            try:
                lines = client.capture_pane(session.tmux_session, tail=40)
            except Exception:
                lines = []
            fingerprint = _pane_fingerprint(lines)
            attach_age = _iso_age_seconds(session.last_attached_at)
            attach_grace_active = (
                session.attachment_state == "attached"
                and attach_age is not None
                and attach_age < ATTACH_ACTIVITY_GRACE_SECONDS
            )
            if fingerprint and fingerprint != session.output_fingerprint and (attachment_changed or attach_grace_active):
                _record_output_fingerprint(session.id, fingerprint)
                session.output_fingerprint = fingerprint
            elif fingerprint and fingerprint != session.output_fingerprint:
                observed_at = datetime.now(UTC).replace(microsecond=0).isoformat()
                _record_output_observation(session.id, fingerprint, observed_at)
                session.output_fingerprint = fingerprint
                session.output_observed_at = observed_at
                idle_age = 0
            else:
                pane_idle_age = _iso_age_seconds(session.output_observed_at)
                idle_age = _min_age(idle_age, pane_idle_age)
        else:
            log_path = Path(session.log_path)
            if log_path.exists():
                lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-40:]

        if lines:
            _refresh_validation_state(session, lines)
        if idle_age is None:
            continue

        if idle_age >= settings.monitor_idle_seconds and session.status not in {SessionStatus.IDLE.value, SessionStatus.WAITING_INPUT.value}:
            update_status(session.id, SessionStatus.IDLE, f"Idle for {idle_age}s")
            touched += 1
        elif idle_age < settings.monitor_idle_seconds and session.status in {SessionStatus.CREATED.value, SessionStatus.STARTING.value, SessionStatus.IDLE.value}:
            update_status(session.id, SessionStatus.RUNNING, "Recent output detected")
            touched += 1

    return touched

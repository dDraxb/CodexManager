from __future__ import annotations

import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from sqlite3 import IntegrityError
from uuid import uuid4

from app.core.constants import SESSIONS_DIR
from app.db.database import get_conn, init_db
from app.models.event import EventRecord
from app.models.session import ALLOWED_TRANSITIONS, SessionMode, SessionRecord, SessionStatus, TERMINAL_STATUSES
from app.runner.client import get_runner_client
from app.runner.contracts import RunnerClient, RunnerError

PROFILES = {"read-only", "safe-edit", "full-agent"}


class SessionError(RuntimeError):
    pass



def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _session_id() -> str:
    return f"sess_{uuid4().hex[:10]}"


def _tmux_session_name(name: str, session_id: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", name.strip()).strip("-").lower() or "session"
    return f"codex-{slug}-{session_id[-6:]}"


def _session_dir(session_id: str) -> Path:
    return SESSIONS_DIR / session_id


def _make_log_file(session_id: str) -> str:
    session_path = _session_dir(session_id)
    session_path.mkdir(parents=True, exist_ok=True)
    log_path = session_path / "output.log"
    log_path.touch(exist_ok=True)
    return str(log_path)


def _event(session_id: str, event_type: str, message: str, metadata: dict | None = None) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO events (session_id, timestamp, type, message, metadata_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, _now_iso(), event_type, message, json.dumps(metadata or {})),
        )


def _row_to_session(row: object | None) -> SessionRecord | None:
    return SessionRecord.from_row(row) if row else None


def _get_session_row(name_or_id: str) -> object | None:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM sessions WHERE id = ? OR name = ? LIMIT 1",
            (name_or_id, name_or_id),
        ).fetchone()


def _transition_status(session: SessionRecord, new_status: SessionStatus, *, note: str | None = None) -> SessionRecord:
    old = session.status
    if old == new_status.value:
        return session
    if old != new_status.value and new_status.value not in ALLOWED_TRANSITIONS.get(old, set()):
        raise SessionError(f"invalid transition: {old} -> {new_status.value}")

    now = _now_iso()
    needs_attention = int(
        new_status.value in {"failed", "lost", "waiting_input"}
        or session.test_status == "failed"
        or session.lint_status == "failed"
    )
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE sessions
            SET status = ?, last_activity_at = ?, last_known_activity = ?,
                finished_at = CASE WHEN ? IN ('finished','failed','stopped') THEN COALESCE(finished_at, ?) ELSE finished_at END,
                needs_attention = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (new_status.value, now, note, new_status.value, now, needs_attention, now, session.id),
        )
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session.id,)).fetchone()
    _event(session.id, "status_changed", f"{old} -> {new_status.value}", {"note": note})
    return SessionRecord.from_row(row)


def create_managed_session(
    *,
    name: str,
    repo_path: str,
    profile: str,
    prompt: str | None,
    approval_policy: str,
    create_worktree_for_writes: bool,
    auto_init_git: bool,
    launch: bool,
    require_changelog: bool = False,
    runner: RunnerClient | None = None,
) -> SessionRecord:
    init_db()
    if profile not in PROFILES:
        raise SessionError(f"invalid profile '{profile}'")

    client = runner or get_runner_client()
    try:
        repo = client.resolve_repo_path(repo_path)
    except RunnerError as exc:
        raise SessionError(str(exc)) from exc

    now = _now_iso()
    session_id = _session_id()
    log_path = _make_log_file(session_id)
    tmux_session = _tmux_session_name(name, session_id)
    allow_write = 0 if profile == "read-only" else 1
    branch = None
    worktree_path = None
    cwd = repo
    changed_files_preview: list[str] = []

    try:
        if create_worktree_for_writes and allow_write:
            branch = f"codex/{name}"
            worktree_path = client.create_worktree(repo, name, branch, auto_init=auto_init_git)
            cwd = worktree_path
        elif auto_init_git:
            client.ensure_git_repo(repo, auto_init=True)
        if require_changelog:
            client.ensure_changelog_entry(cwd, name, prompt, now)
    except RunnerError as exc:
        raise SessionError(str(exc)) from exc

    try:
        branch = branch or client.current_branch(repo, cwd)
    except RunnerError:
        branch = branch or None

    try:
        changed_files_preview = client.changed_files(repo, cwd)
    except RunnerError:
        changed_files_preview = []

    try:
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO sessions (
                  id, name, mode, status, codex_session_id, codex_rollout_path, codex_updated_at, repo_path, worktree_path, branch,
                  profile, approval_policy, allow_write, allow_shell, tmux_session, pid,
                  prompt, created_at, started_at, finished_at, last_activity_at,
                  last_known_activity, changed_files_count, changed_files_preview,
                  test_status, lint_status, exit_code, log_path, cwd, target_label,
                  observability, needs_attention, require_changelog, attachment_state, last_attached_at, last_detached_at,
                  output_fingerprint, output_observed_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    name,
                    SessionMode.MANAGED.value,
                    SessionStatus.CREATED.value,
                    None,
                    None,
                    None,
                    repo,
                    worktree_path,
                    branch,
                    profile,
                    approval_policy,
                    allow_write,
                    1,
                    tmux_session,
                    None,
                    prompt,
                    now,
                    None,
                    None,
                    now,
                    "Session created",
                    len(changed_files_preview),
                    json.dumps(changed_files_preview[:10]),
                    "unknown",
                    "unknown",
                    None,
                    log_path,
                    cwd,
                    Path(repo).name,
                    "full",
                    0,
                    1 if require_changelog else 0,
                    "detached",
                    None,
                    now,
                    None,
                    None,
                    now,
                ),
            )
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    except IntegrityError as exc:
        raise SessionError(f"session name or tmux session already exists: {name}") from exc

    session = SessionRecord.from_row(row)
    _event(
        session.id,
        "session_created",
        f"Session '{name}' created",
        {"require_changelog": require_changelog},
    )
    _event(session.id, "worktree_created", "Worktree created", {"path": worktree_path, "branch": branch}) if worktree_path else None

    if not launch:
        return session

    session = _transition_status(session, SessionStatus.STARTING, note="Launching Codex in tmux")
    try:
        launch_cmd = client.build_codex_launch_command(profile, prompt)
    except RunnerError as exc:
        session = _transition_status(session, SessionStatus.FAILED, note=f"Launch failed: {exc}")
        raise SessionError(str(exc)) from exc

    try:
        client.create_session(session.tmux_session or tmux_session, session.cwd or repo, session.log_path, launch_cmd)
    except RunnerError as exc:
        session = _transition_status(session, SessionStatus.FAILED, note=f"Launch failed: {exc}")
        with get_conn() as conn:
            conn.execute("UPDATE sessions SET exit_code = ?, updated_at = ? WHERE id = ?", (1, _now_iso(), session.id))
        _event(session.id, "process_exited", "Codex launch failed", {"error": str(exc)})
        raise SessionError(str(exc)) from exc

    pid = client.pane_pid(session.tmux_session or tmux_session)
    with get_conn() as conn:
        conn.execute(
            "UPDATE sessions SET pid = ?, started_at = ?, updated_at = ? WHERE id = ?",
            (pid, _now_iso(), _now_iso(), session.id),
        )
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session.id,)).fetchone()
    session = SessionRecord.from_row(row)
    _event(session.id, "tmux_session_started", "tmux session started", {"tmux_session": session.tmux_session, "pid": pid})
    return session


def adopt_session(
    *,
    name: str,
    codex_session_id: str,
    repo_path: str,
    profile: str = "read-only",
    runner: RunnerClient | None = None,
) -> SessionRecord:
    init_db()
    if profile not in PROFILES:
        raise SessionError(f"invalid profile '{profile}'")

    client = runner or get_runner_client()
    try:
        repo = client.resolve_repo_path(repo_path)
    except RunnerError as exc:
        raise SessionError(str(exc)) from exc

    now = _now_iso()
    session_id = _session_id()
    log_path = _make_log_file(session_id)
    tmux_session = _tmux_session_name(name, session_id)
    branch = None

    try:
        branch = client.current_branch(repo, repo)
    except RunnerError:
        branch = None

    try:
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO sessions (
                  id, name, mode, status, codex_session_id, codex_rollout_path, codex_updated_at, repo_path, worktree_path, branch,
                  profile, approval_policy, allow_write, allow_shell, tmux_session, pid,
                  prompt, created_at, started_at, finished_at, last_activity_at,
                  last_known_activity, changed_files_count, changed_files_preview,
                  test_status, lint_status, exit_code, log_path, cwd, target_label,
                  observability, needs_attention, require_changelog, attachment_state, last_attached_at, last_detached_at,
                  output_fingerprint, output_observed_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    name,
                    SessionMode.ADOPTED.value,
                    SessionStatus.IDLE.value,
                    codex_session_id,
                    None,
                    None,
                    repo,
                    None,
                    branch,
                    profile,
                    "on-request",
                    0 if profile == "read-only" else 1,
                    1,
                    tmux_session,
                    None,
                    None,
                    now,
                    None,
                    None,
                    now,
                    "Adopted session",
                    0,
                    "[]",
                    "unknown",
                    "unknown",
                    None,
                    log_path,
                    repo,
                    Path(repo).name,
                    "reduced",
                    0,
                    0,
                    "detached",
                    None,
                    now,
                    None,
                    None,
                    now,
                ),
            )
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    except IntegrityError as exc:
        raise SessionError(f"session name already exists: {name}") from exc

    session = SessionRecord.from_row(row)
    _event(session.id, "session_adopted", f"Session '{name}' adopted", {"codex_session_id": codex_session_id})
    return session


def list_sessions() -> list[SessionRecord]:
    init_db()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM sessions ORDER BY datetime(updated_at) DESC"
        ).fetchall()
    return [SessionRecord.from_row(row) for row in rows]


def get_session(name_or_id: str) -> SessionRecord | None:
    init_db()
    return _row_to_session(_get_session_row(name_or_id))


def open_session(name_or_id: str, runner: RunnerClient | None = None) -> str:
    session = get_session(name_or_id)
    if session is None:
        raise SessionError(f"session '{name_or_id}' not found")
    if not session.tmux_session:
        raise SessionError("session has no tmux binding")
    if session.mode == SessionMode.ADOPTED.value and not session.started_at:
        raise SessionError("adopted session is not running in tmux yet; use Resume first")
    client = runner or get_runner_client()
    if not client.session_exists(session.tmux_session):
        raise SessionError("tmux session is not running")

    _event(session.id, "session_opened", "Attach command requested", {"tmux_session": session.tmux_session})
    return client.attach_command(session.tmux_session)


def set_codex_session_id(
    name_or_id: str,
    codex_session_id: str,
    *,
    codex_rollout_path: str | None = None,
    codex_updated_at: int | None = None,
) -> SessionRecord:
    session = get_session(name_or_id)
    if session is None:
        raise SessionError(f"session '{name_or_id}' not found")
    if not codex_session_id.strip():
        raise SessionError("codex session id is required")

    now = _now_iso()
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE sessions
            SET codex_session_id = ?, codex_rollout_path = ?, codex_updated_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (codex_session_id.strip(), codex_rollout_path, codex_updated_at, now, session.id),
        )
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session.id,)).fetchone()
    _event(
        session.id,
        "codex_session_linked",
        "Codex history target updated",
        {
            "codex_session_id": codex_session_id.strip(),
            "codex_rollout_path": codex_rollout_path,
            "codex_updated_at": codex_updated_at,
            "source": "manual",
        },
    )
    return SessionRecord.from_row(row)


def _build_history_resume_command(session: SessionRecord, client: RunnerClient) -> str:
    launch_cmd = client.build_codex_launch_command(session.profile, None)
    if not launch_cmd.startswith("codex "):
        return "printf 'codex not found on PATH. Attach and continue manually.\\n'; sleep 86400"
    return f"{launch_cmd} resume {session.codex_session_id}"


def resume_session(name_or_id: str, runner: RunnerClient | None = None) -> tuple[SessionRecord, str]:
    session = get_session(name_or_id)
    if session is None:
        raise SessionError(f"session '{name_or_id}' not found")

    client = runner or get_runner_client()
    if session.tmux_session and client.session_exists(session.tmux_session):
        if session.started_at is None:
            pid = client.pane_pid(session.tmux_session)
            now = _now_iso()
            with get_conn() as conn:
                conn.execute(
                    "UPDATE sessions SET pid = COALESCE(pid, ?), started_at = COALESCE(started_at, ?), updated_at = ? WHERE id = ?",
                    (pid, now, now, session.id),
                )
                row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session.id,)).fetchone()
            session = SessionRecord.from_row(row)
        cmd = client.attach_command(session.tmux_session)
        _event(session.id, "session_resumed", "Reattached to existing tmux session")
        return session, cmd

    if session.codex_session_id and session.tmux_session:
        launch_cmd = _build_history_resume_command(session, client)
        try:
            client.create_session(session.tmux_session, session.cwd or session.repo_path, session.log_path, launch_cmd)
        except RunnerError as exc:
            raise SessionError(f"failed to resume session from Codex history: {exc}") from exc
        pid = client.pane_pid(session.tmux_session)
        now = _now_iso()
        with get_conn() as conn:
            conn.execute(
                "UPDATE sessions SET pid = ?, started_at = COALESCE(started_at, ?), updated_at = ? WHERE id = ?",
                (pid, now, now, session.id),
            )
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session.id,)).fetchone()
        session = SessionRecord.from_row(row)
        session = _transition_status(session, SessionStatus.RUNNING, note="Resumed from Codex history")
        _event(
            session.id,
            "session_resumed",
            "Session resumed from Codex history in tmux",
            {
                "codex_session_id": session.codex_session_id,
                "codex_rollout_path": session.codex_rollout_path,
            },
        )
        return session, client.attach_command(session.tmux_session)

    raise SessionError("session cannot be resumed automatically")


def stop_session(name_or_id: str, runner: RunnerClient | None = None) -> SessionRecord:
    session = get_session(name_or_id)
    if session is None:
        raise SessionError(f"session '{name_or_id}' not found")

    client = runner or get_runner_client()
    if session.tmux_session and client.session_exists(session.tmux_session):
        client.stop_session(session.tmux_session)
        _event(session.id, "tmux_session_stopped", "tmux session stopped")

    with get_conn() as conn:
        conn.execute("UPDATE sessions SET exit_code = ?, updated_at = ? WHERE id = ?", (0, _now_iso(), session.id))
    session = get_session(session.id)
    if session is None:
        raise SessionError("session vanished while stopping")

    if session.status not in TERMINAL_STATUSES:
        session = _transition_status(session, SessionStatus.STOPPED, note="Stopped by user")
    _event(session.id, "session_stopped", f"Session '{session.name}' stopped")
    return session


def refresh_git_state(session: SessionRecord, runner: RunnerClient | None = None) -> SessionRecord:
    client = runner or get_runner_client()
    try:
        files = client.changed_files(session.repo_path, session.cwd)
        branch = session.branch or client.current_branch(session.repo_path, session.cwd)
    except RunnerError:
        files = []
        branch = session.branch

    with get_conn() as conn:
        conn.execute(
            """
            UPDATE sessions
            SET branch = COALESCE(?, branch), changed_files_count = ?, changed_files_preview = ?, updated_at = ?
            WHERE id = ?
            """,
            (branch, len(files), json.dumps(files[:10]), _now_iso(), session.id),
        )
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session.id,)).fetchone()
    return SessionRecord.from_row(row)


def capture_session_logs(session_id: str, tail: int = 200, *, runner: RunnerClient | None = None) -> list[str]:
    session = get_session(session_id)
    if session is None:
        raise SessionError("session not found")

    client = runner or get_runner_client()
    if session.tmux_session:
        try:
            exists = client.session_exists(session.tmux_session)
            lines = client.capture_pane(session.tmux_session, tail=tail) if exists else []
        except RunnerError:
            lines = []
        if lines:
            return _trim_trailing_blank_lines(lines[-tail:])

    path = Path(session.log_path)
    if not path.exists():
        return []
    return _trim_trailing_blank_lines(path.read_text(encoding="utf-8", errors="replace").splitlines()[-tail:])


def _trim_trailing_blank_lines(lines: list[str]) -> list[str]:
    trimmed = list(lines)
    while trimmed and not trimmed[-1].strip():
        trimmed.pop()
    return trimmed


def list_events(session_id: str, limit: int = 100) -> list[EventRecord]:
    init_db()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM events WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
    return [EventRecord.from_row(row) for row in rows]


def update_status(name_or_id: str, status: SessionStatus, note: str) -> SessionRecord:
    session = get_session(name_or_id)
    if session is None:
        raise SessionError(f"session '{name_or_id}' not found")
    return _transition_status(session, status, note=note)


def delete_session(name_or_id: str, runner: RunnerClient | None = None) -> str:
    session = get_session(name_or_id)
    if session is None:
        raise SessionError(f"session '{name_or_id}' not found")

    client = runner or get_runner_client()
    if session.tmux_session and client.session_exists(session.tmux_session):
        client.stop_session(session.tmux_session)

    with get_conn() as conn:
        conn.execute("DELETE FROM sessions WHERE id = ?", (session.id,))

    shutil.rmtree(_session_dir(session.id), ignore_errors=True)
    return session.name


def delete_sessions_by_predicate(predicate, *, runner: RunnerClient | None = None) -> list[str]:
    client = runner or get_runner_client()
    deleted: list[str] = []
    for session in list_sessions():
        if not predicate(session):
            continue
        if session.tmux_session and client.session_exists(session.tmux_session):
            client.stop_session(session.tmux_session)
        with get_conn() as conn:
            conn.execute("DELETE FROM sessions WHERE id = ?", (session.id,))
        shutil.rmtree(_session_dir(session.id), ignore_errors=True)
        deleted.append(session.name)
    return deleted


def delete_stopped_sessions(*, runner: RunnerClient | None = None) -> list[str]:
    return delete_sessions_by_predicate(
        lambda session: session.status == SessionStatus.STOPPED.value,
        runner=runner,
    )


def delete_test_named_sessions(*, runner: RunnerClient | None = None) -> list[str]:
    return delete_sessions_by_predicate(
        lambda session: "test" in session.name.lower(),
        runner=runner,
    )

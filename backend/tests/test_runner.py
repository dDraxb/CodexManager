from __future__ import annotations

import io
import os
import sqlite3
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient


class _FakeUrlopenResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeUrlopenResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def _bridge_urlopen(monkeypatch, client: TestClient, base_url: str) -> None:
    def fake_urlopen(request: urllib.request.Request):
        url = request.full_url
        assert url.startswith(base_url)
        path = url[len(base_url):] or "/"
        body = request.data or b""
        response = client.post(path, content=body, headers=dict(request.header_items()))
        payload = response.content
        if response.status_code >= 400:
            raise urllib.error.HTTPError(
                url,
                response.status_code,
                response.reason_phrase,
                response.headers,
                io.BytesIO(payload),
            )
        return _FakeUrlopenResponse(payload)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)


class RecordingRunner:
    def __init__(self, repo_path: str, *, session_exists: bool = True) -> None:
        self.repo_path = repo_path
        self.session_exists_value = session_exists
        self.calls: list[tuple] = []

    def resolve_repo_path(self, repo_path: str) -> str:
        self.calls.append(("resolve_repo_path", repo_path))
        return self.repo_path

    def build_codex_launch_command(self, profile: str, prompt: str | None) -> str:
        self.calls.append(("build_codex_launch_command", profile, prompt))
        return "codex --profile safe-edit"

    def ensure_git_repo(self, repo_path: str, auto_init: bool = False) -> None:
        self.calls.append(("ensure_git_repo", repo_path, auto_init))

    def create_worktree(self, repo_path: str, session_name: str, branch: str, auto_init: bool = False) -> str:
        self.calls.append(("create_worktree", repo_path, session_name, branch, auto_init))
        return f"{repo_path}-worktree"

    def changed_files(self, repo_path: str, cwd: str | None) -> list[str]:
        self.calls.append(("changed_files", repo_path, cwd))
        return ["README.md"]

    def current_branch(self, repo_path: str, cwd: str | None) -> str | None:
        self.calls.append(("current_branch", repo_path, cwd))
        return "main"

    def ensure_changelog_entry(self, repo_path: str, session_name: str, prompt: str | None, timestamp: str) -> str:
        self.calls.append(("ensure_changelog_entry", repo_path, session_name, prompt, timestamp))
        return f"{repo_path}/CHANGELOG.md"

    def detect_validation_recipe(self, repo_path: str) -> dict | None:
        self.calls.append(("detect_validation_recipe", repo_path))
        return None

    def find_recent_codex_session(self, cwd: str, prompt: str | None, since: str | None) -> str | None:
        self.calls.append(("find_recent_codex_session", cwd, prompt, since))
        return None

    def list_codex_threads(self, cwd: str | None, query: str | None, limit: int = 20) -> list[dict]:
        self.calls.append(("list_codex_threads", cwd, query, limit))
        return []

    def list_resume_candidates(self, thread_id: str | None, cwd: str | None, prompt: str | None, limit: int = 12) -> list[dict]:
        self.calls.append(("list_resume_candidates", thread_id, cwd, prompt, limit))
        if thread_id:
            return [
                {
                    "id": thread_id,
                    "cwd": cwd,
                    "created_at": 1,
                    "updated_at": 2,
                    "title": prompt or "resume target",
                    "first_user_message": prompt or "resume target",
                    "rollout_path": "/tmp/rollout.jsonl",
                }
            ]
        return []

    def session_exists(self, session_name: str) -> bool:
        self.calls.append(("session_exists", session_name))
        return self.session_exists_value

    def create_session(self, session_name: str, cwd: str, log_path: str, launch_cmd: str | None) -> None:
        self.calls.append(("create_session", session_name, cwd, log_path, launch_cmd))

    def stop_session(self, session_name: str) -> None:
        self.calls.append(("stop_session", session_name))

    def attach_command(self, session_name: str) -> str:
        self.calls.append(("attach_command", session_name))
        return f"tmux attach -t {session_name}"

    def pane_pid(self, session_name: str) -> int | None:
        self.calls.append(("pane_pid", session_name))
        return 4321

    def capture_pane(self, session_name: str, tail: int = 200) -> list[str]:
        self.calls.append(("capture_pane", session_name, tail))
        return ["pane output"]

    def is_session_attached(self, session_name: str) -> bool:
        self.calls.append(("is_session_attached", session_name))
        return False


def test_local_runner_can_prepare_git_repo_and_worktree(configured_modules, tmp_path):
    from app.runner.client import LocalRunnerClient

    folder = tmp_path / "plain-folder"
    folder.mkdir()
    (folder / "notes.txt").write_text("hello\n", encoding="utf-8")

    runner = LocalRunnerClient()
    repo = runner.resolve_repo_path(str(folder))
    runner.ensure_git_repo(repo, auto_init=True)
    worktree = runner.create_worktree(repo, "local-task", "codex/local-task")

    assert (folder / ".git").exists()
    assert Path(worktree).exists()


def test_local_runner_lists_codex_threads_for_repo_subpaths(configured_modules, tmp_path, monkeypatch):
    from app.runner.client import LocalRunnerClient

    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    state_db = codex_home / "state_5.sqlite"
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    with sqlite3.connect(state_db) as conn:
        conn.execute(
            """
            CREATE TABLE threads (
                id TEXT PRIMARY KEY,
                cwd TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                first_user_message TEXT,
                title TEXT,
                rollout_path TEXT
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO threads (id, cwd, created_at, updated_at, first_user_message, title, rollout_path)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "parent",
                    "/repo/service-a",
                    100,
                    200,
                    "parent thread",
                    "parent thread",
                    "/tmp/parent.jsonl",
                ),
                (
                    "child",
                    "/repo/service-a/packages/api",
                    110,
                    210,
                    "child thread",
                    "child thread",
                    "/tmp/child.jsonl",
                ),
                (
                    "other",
                    "/repo/service-b",
                    120,
                    220,
                    "other thread",
                    "other thread",
                    "/tmp/other.jsonl",
                ),
            ],
        )

    runner = LocalRunnerClient()
    threads = runner.list_codex_threads("/repo/service-a", None, limit=10)

    assert [thread["id"] for thread in threads] == ["child", "parent"]


def test_create_managed_session_accepts_runner_owned_repo_paths(configured_modules):
    from app.services.sessions import create_managed_session

    runner = RecordingRunner("/host/repos/service-a")

    session = create_managed_session(
        name="remote-owned-path",
        repo_path="/container/cannot/see/this",
        profile="safe-edit",
        prompt="Refactor service",
        approval_policy="on-request",
        create_worktree_for_writes=True,
        auto_init_git=False,
        launch=False,
        runner=runner,
    )

    assert session.repo_path == "/host/repos/service-a"
    assert session.worktree_path == "/host/repos/service-a-worktree"
    assert session.branch == "codex/remote-owned-path"
    assert ("resolve_repo_path", "/container/cannot/see/this") in runner.calls
    assert ("create_worktree", "/host/repos/service-a", "remote-owned-path", "codex/remote-owned-path", False) in runner.calls


def test_create_managed_session_launch_stays_starting_until_activity(configured_modules, git_repo):
    from app.models.session import SessionStatus
    from app.services.sessions import create_managed_session, list_events

    runner = RecordingRunner(str(git_repo), session_exists=True)

    session = create_managed_session(
        name="launch-stays-starting",
        repo_path=str(git_repo),
        profile="safe-edit",
        prompt="Refactor service",
        approval_policy="on-request",
        create_worktree_for_writes=False,
        auto_init_git=False,
        launch=True,
        runner=runner,
    )

    assert session.status == SessionStatus.STARTING.value
    assert session.work_phase == "planning"
    assert session.work_phase_confidence == "low"
    assert session.last_major_phase == "planning"
    assert session.last_major_phase_confidence == "low"
    assert session.health_label == "healthy"
    assert session.priority_score == 46
    events = list_events(session.id)
    assert any(event.type == "tmux_session_started" for event in events)
    assert not any(event.type == "status_changed" and event.message == "starting -> running" for event in events)


def test_reconcile_once_uses_runner_for_tmux_presence(configured_modules, git_repo):
    from app.models.session import SessionStatus
    from app.monitoring.reconciler import reconcile_once
    from app.services.sessions import create_managed_session, get_session, list_events

    runner = RecordingRunner(str(git_repo), session_exists=False)

    session = create_managed_session(
        name="lost-managed-session",
        repo_path=str(git_repo),
        profile="read-only",
        prompt=None,
        approval_policy="on-request",
        create_worktree_for_writes=False,
        auto_init_git=False,
        launch=False,
        runner=runner,
    )

    touched = reconcile_once(runner=runner)
    refreshed = get_session(session.id)

    assert touched == 1
    assert refreshed is not None
    assert refreshed.status == SessionStatus.LOST.value
    assert ("session_exists", refreshed.tmux_session) in runner.calls

    events = list_events(session.id)
    initial_status_events = [event for event in events if event.type == "status_changed" and event.message == "created -> lost"]
    assert len(initial_status_events) == 1

    touched = reconcile_once(runner=runner)
    refreshed = get_session(session.id)

    assert touched == 0
    assert refreshed is not None
    assert refreshed.status == SessionStatus.LOST.value

    events = list_events(session.id)
    lost_to_lost_events = [event for event in events if event.type == "status_changed" and event.message == "lost -> lost"]
    assert lost_to_lost_events == []


def test_reconcile_once_marks_missing_tmux_session_as_detached(configured_modules, git_repo):
    from app.db.database import get_conn
    from app.monitoring.reconciler import reconcile_once
    from app.services.sessions import create_managed_session, get_session, list_events

    runner = RecordingRunner(str(git_repo), session_exists=False)

    session = create_managed_session(
        name="missing-attached-session",
        repo_path=str(git_repo),
        profile="read-only",
        prompt=None,
        approval_policy="on-request",
        create_worktree_for_writes=False,
        auto_init_git=False,
        launch=False,
        runner=runner,
    )

    with get_conn() as conn:
        conn.execute(
            "UPDATE sessions SET attachment_state = ?, last_attached_at = ?, updated_at = ? WHERE id = ?",
            ("attached", "2026-03-13T21:07:43+00:00", "2026-03-13T21:07:43+00:00", session.id),
        )

    reconcile_once(runner=runner)
    refreshed = get_session(session.id)

    assert refreshed is not None
    assert refreshed.status == "lost"
    assert refreshed.attachment_state == "detached"
    assert refreshed.last_detached_at is not None

    events = list_events(session.id)
    attachment_events = [event for event in events if event.type == "attachment_changed" and event.message == "Session detached"]
    assert len(attachment_events) == 1


def test_reconcile_once_does_not_wake_newly_adopted_session_without_output(configured_modules, git_repo):
    from app.monitoring.reconciler import reconcile_once
    from app.services.sessions import adopt_session, get_session

    runner = RecordingRunner(str(git_repo), session_exists=False)

    session = adopt_session(
        name="adopted-idle-session",
        codex_session_id="cdx_123",
        repo_path=str(git_repo),
        runner=runner,
    )

    touched = reconcile_once(runner=runner)
    refreshed = get_session(session.id)

    assert touched == 0
    assert refreshed is not None
    assert refreshed.status == "idle"


def test_resume_adopted_session_persists_started_at_and_pid(configured_modules, git_repo):
    from app.services.sessions import adopt_session, get_session, resume_session

    runner = RecordingRunner(str(git_repo), session_exists=False)

    session = adopt_session(
        name="resume-adopted-session",
        codex_session_id="cdx_123",
        repo_path=str(git_repo),
        runner=runner,
    )

    resumed, command = resume_session(session.id, runner=runner)
    refreshed = get_session(session.id)

    assert resumed.status == "running"
    assert command == f"tmux attach -t {session.tmux_session}"
    assert refreshed is not None
    assert refreshed.started_at is not None
    assert refreshed.pid == 4321
    assert refreshed.codex_rollout_path is None


def test_resume_managed_session_can_fall_back_to_codex_history(configured_modules, git_repo):
    from app.services.sessions import create_managed_session, get_session, resume_session, set_codex_session_id

    runner = RecordingRunner(str(git_repo), session_exists=False)

    session = create_managed_session(
        name="resume-managed-history-session",
        repo_path=str(git_repo),
        profile="safe-edit",
        prompt="Refactor service layer",
        approval_policy="on-request",
        create_worktree_for_writes=False,
        auto_init_git=False,
        launch=False,
        runner=runner,
    )
    session = set_codex_session_id(
        session.id,
        "019ce115-d070-7053-b385-870d5e021ea7",
        codex_rollout_path="/tmp/rollout.jsonl",
        codex_updated_at=2,
    )

    resumed, command = resume_session(session.id, runner=runner)
    refreshed = get_session(session.id)

    assert resumed.status == "running"
    assert command == f"tmux attach -t {session.tmux_session}"
    assert refreshed is not None
    assert refreshed.started_at is not None
    assert refreshed.pid == 4321
    assert any(
        call[0] == "create_session"
        and call[4] == "codex --profile safe-edit resume 019ce115-d070-7053-b385-870d5e021ea7"
        for call in runner.calls
    )


def test_reconcile_once_moves_idle_session_to_running_on_new_pane_output(configured_modules, git_repo):
    from app.models.session import SessionStatus
    from app.monitoring.reconciler import reconcile_once
    from app.services.sessions import create_managed_session, get_session, update_status

    runner = RecordingRunner(str(git_repo), session_exists=True)

    session = create_managed_session(
        name="wake-idle-session",
        repo_path=str(git_repo),
        profile="read-only",
        prompt=None,
        approval_policy="on-request",
        create_worktree_for_writes=False,
        auto_init_git=False,
        launch=True,
        runner=runner,
    )
    update_status(session.id, SessionStatus.IDLE, "Idle for 999s")
    old_ts = (datetime.now(UTC) - timedelta(seconds=900)).timestamp()
    os.utime(session.log_path, (old_ts, old_ts))

    touched = reconcile_once(runner=runner)
    refreshed = get_session(session.id)

    assert touched == 1
    assert refreshed is not None
    assert refreshed.status == SessionStatus.RUNNING.value
    assert refreshed.output_fingerprint is not None
    assert refreshed.output_observed_at is not None


def test_reconcile_once_updates_attachment_state(configured_modules, git_repo):
    from app.monitoring.reconciler import reconcile_once
    from app.services.sessions import create_managed_session, get_session

    class AttachedRunner(RecordingRunner):
        def is_session_attached(self, session_name: str) -> bool:
            self.calls.append(("is_session_attached", session_name))
            return True

    runner = AttachedRunner(str(git_repo), session_exists=True)

    session = create_managed_session(
        name="attached-session",
        repo_path=str(git_repo),
        profile="read-only",
        prompt=None,
        approval_policy="on-request",
        create_worktree_for_writes=False,
        auto_init_git=False,
        launch=True,
        runner=runner,
    )

    reconcile_once(runner=runner)
    refreshed = get_session(session.id)

    assert refreshed is not None
    assert refreshed.attachment_state == "attached"
    assert refreshed.last_attached_at is not None


def test_reconcile_once_updates_validation_status_and_attention(configured_modules, git_repo):
    from app.monitoring.reconciler import reconcile_once
    from app.services.sessions import create_managed_session, get_session, list_events, list_validation_history

    class ValidationRunner(RecordingRunner):
        def capture_pane(self, session_name: str, tail: int = 200) -> list[str]:
            self.calls.append(("capture_pane", session_name, tail))
            return [
                "$ pytest",
                "============================== 4 passed in 0.20s ==============================",
                "$ ruff check .",
                "Would reformat: backend/app/api/server.py",
                "Found 1 error.",
            ]

    runner = ValidationRunner(str(git_repo), session_exists=True)

    session = create_managed_session(
        name="validation-session",
        repo_path=str(git_repo),
        profile="read-only",
        prompt=None,
        approval_policy="on-request",
        create_worktree_for_writes=False,
        auto_init_git=False,
        launch=True,
        runner=runner,
    )

    reconcile_once(runner=runner)
    refreshed = get_session(session.id)

    assert refreshed is not None
    assert refreshed.test_status == "passed"
    assert refreshed.lint_status == "failed"
    assert refreshed.work_phase == "testing"
    assert refreshed.work_phase_confidence == "high"
    assert refreshed.last_major_phase == "testing"
    assert refreshed.last_major_phase_confidence == "high"
    assert refreshed.health_label == "attention"
    assert refreshed.priority_score >= 88
    assert refreshed.needs_attention == 1

    events = list_events(session.id)
    validation_events = [event.message for event in events if event.type == "validation_changed"]
    assert "Tests passed" in validation_events
    assert "Lint failed" in validation_events
    assert any(event.type == "work_phase_changed" and event.message == "Phase -> testing" for event in events)
    history = list_validation_history(session.id, limit=10)
    assert any(entry.kind == "tests" and entry.status == "passed" for entry in history)
    assert any(entry.kind == "lint" and entry.status == "failed" for entry in history)


def test_reconcile_once_backfills_validation_result_from_full_log(configured_modules, git_repo):
    from pathlib import Path

    from app.monitoring.reconciler import reconcile_once
    from app.services.sessions import create_managed_session, get_session

    class QuietRunner(RecordingRunner):
        def capture_pane(self, session_name: str, tail: int = 200) -> list[str]:
            self.calls.append(("capture_pane", session_name, tail))
            return ["Session is idle now."]

    runner = QuietRunner(str(git_repo), session_exists=True)

    session = create_managed_session(
        name="validation-backfill-session",
        repo_path=str(git_repo),
        profile="read-only",
        prompt=None,
        approval_policy="on-request",
        create_worktree_for_writes=False,
        auto_init_git=False,
        launch=True,
        runner=runner,
    )
    Path(session.log_path).write_text(
        "\n".join(
            [
                "Earlier output",
                "• Ran ./bin/smoke_test.sh",
                "[6/6] PASS",
                "Smoke test succeeded.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    reconcile_once(runner=runner)
    refreshed = get_session(session.id)

    assert refreshed is not None
    assert refreshed.test_activity == "none"
    assert refreshed.test_status == "passed"
    assert refreshed.test_status_at is not None


def test_reconcile_once_marks_blocked_phase_from_environment_errors(configured_modules, git_repo):
    from app.monitoring.reconciler import reconcile_once
    from app.services.sessions import create_managed_session, get_session

    class BlockedRunner(RecordingRunner):
        def capture_pane(self, session_name: str, tail: int = 200) -> list[str]:
            self.calls.append(("capture_pane", session_name, tail))
            return [
                "Running smoke flow",
                "Smoke test is blocked on missing environment variable",
                "command not found: codex",
            ]

    runner = BlockedRunner(str(git_repo), session_exists=True)

    session = create_managed_session(
        name="blocked-phase-session",
        repo_path=str(git_repo),
        profile="read-only",
        prompt=None,
        approval_policy="on-request",
        create_worktree_for_writes=False,
        auto_init_git=False,
        launch=True,
        runner=runner,
    )

    reconcile_once(runner=runner)
    refreshed = get_session(session.id)

    assert refreshed is not None
    assert refreshed.work_phase == "blocked"
    assert refreshed.work_phase_confidence == "high"
    assert refreshed.last_major_phase == "blocked"
    assert refreshed.last_major_phase_confidence == "high"
    assert refreshed.block_category == "tooling"
    assert refreshed.block_reason == "command not found"
    assert refreshed.health_label == "attention"
    assert refreshed.priority_score >= 95


def test_reconcile_once_flags_same_repo_live_session_conflict(configured_modules, git_repo):
    from app.monitoring.reconciler import reconcile_once
    from app.services.sessions import create_managed_session, get_session

    class OverlapRunner(RecordingRunner):
        def changed_files(self, repo_path: str, cwd: str | None) -> list[str]:
            self.calls.append(("changed_files", repo_path, cwd))
            if cwd and "repo-conflict-a" in cwd:
                return ["backend/app/api/server.py", "README.md"]
            return ["backend/app/api/server.py"]

    runner = OverlapRunner(str(git_repo), session_exists=True)

    session_a = create_managed_session(
        name="repo-conflict-a",
        repo_path=str(git_repo),
        profile="safe-edit",
        prompt=None,
        approval_policy="on-request",
        create_worktree_for_writes=False,
        auto_init_git=False,
        launch=True,
        runner=runner,
    )
    session_b = create_managed_session(
        name="repo-conflict-b",
        repo_path=str(git_repo),
        profile="safe-edit",
        prompt=None,
        approval_policy="on-request",
        create_worktree_for_writes=False,
        auto_init_git=False,
        launch=True,
        runner=runner,
    )

    reconcile_once(runner=runner)
    refreshed_a = get_session(session_a.id)
    refreshed_b = get_session(session_b.id)

    assert refreshed_a is not None and refreshed_b is not None
    assert refreshed_a.repo_risk_label == "high"
    assert refreshed_b.repo_risk_label == "high"
    assert refreshed_a.repo_risk_reason == "multiple live sessions are changing the same files without isolation: backend/app/api/server.py"
    assert refreshed_b.repo_risk_reason == "multiple live sessions are changing the same files without isolation: backend/app/api/server.py"


def test_reconcile_once_links_managed_session_to_codex_history(configured_modules, git_repo):
    from app.monitoring.reconciler import reconcile_once
    from app.services.sessions import create_managed_session, get_session, list_events

    class LinkingRunner(RecordingRunner):
        def find_recent_codex_session(self, cwd: str, prompt: str | None, since: str | None) -> str | None:
            self.calls.append(("find_recent_codex_session", cwd, prompt, since))
            return "019ce115-d070-7053-b385-870d5e021ea7"

    runner = LinkingRunner(str(git_repo), session_exists=True)

    session = create_managed_session(
        name="capture-codex-session-id",
        repo_path=str(git_repo),
        profile="safe-edit",
        prompt="Refactor service layer",
        approval_policy="on-request",
        create_worktree_for_writes=False,
        auto_init_git=False,
        launch=True,
        runner=runner,
    )

    reconcile_once(runner=runner)
    refreshed = get_session(session.id)

    assert refreshed is not None
    assert refreshed.codex_session_id == "019ce115-d070-7053-b385-870d5e021ea7"
    assert refreshed.codex_rollout_path == "/tmp/rollout.jsonl"
    assert refreshed.codex_updated_at == 2
    assert any(call[0] == "find_recent_codex_session" and call[1] == str(git_repo) for call in runner.calls)

    events = list_events(session.id)
    assert any(
        event.type == "codex_session_linked" and "019ce115-d070-7053-b385-870d5e021ea7" in event.metadata_json
        for event in events
    )


def test_reconcile_once_backfills_codex_history_metadata_for_existing_session(configured_modules, git_repo):
    from app.monitoring.reconciler import reconcile_once
    from app.services.sessions import create_managed_session, get_session, list_events, set_codex_session_id

    runner = RecordingRunner(str(git_repo), session_exists=False)

    session = create_managed_session(
        name="backfill-codex-history-target",
        repo_path=str(git_repo),
        profile="safe-edit",
        prompt="Refactor service layer",
        approval_policy="on-request",
        create_worktree_for_writes=False,
        auto_init_git=False,
        launch=False,
        runner=runner,
    )
    set_codex_session_id(session.id, "019ce115-d070-7053-b385-870d5e021ea7")

    reconcile_once(runner=runner)
    refreshed = get_session(session.id)

    assert refreshed is not None
    assert refreshed.codex_rollout_path == "/tmp/rollout.jsonl"
    assert refreshed.codex_updated_at == 2

    events = list_events(session.id)
    assert any(event.type == "codex_history_backfilled" for event in events)


def test_reconcile_once_does_not_wake_idle_session_on_attachment_only(configured_modules, git_repo):
    from app.models.session import SessionStatus
    from app.monitoring.reconciler import reconcile_once
    from app.services.sessions import create_managed_session, get_session, update_status

    class AttachOnlyRunner(RecordingRunner):
        def __init__(self, repo_path: str, *, session_exists: bool = True) -> None:
            super().__init__(repo_path, session_exists=session_exists)
            self._attached = True

        def is_session_attached(self, session_name: str) -> bool:
            self.calls.append(("is_session_attached", session_name))
            return self._attached

        def capture_pane(self, session_name: str, tail: int = 200) -> list[str]:
            self.calls.append(("capture_pane", session_name, tail))
            return ["pane output after attach repaint"]

    runner = AttachOnlyRunner(str(git_repo), session_exists=True)

    session = create_managed_session(
        name="attach-only-session",
        repo_path=str(git_repo),
        profile="read-only",
        prompt=None,
        approval_policy="on-request",
        create_worktree_for_writes=False,
        auto_init_git=False,
        launch=True,
        runner=runner,
    )
    update_status(session.id, SessionStatus.IDLE, "Idle for 999s")
    old_ts = (datetime.now(UTC) - timedelta(seconds=900)).timestamp()
    os.utime(session.log_path, (old_ts, old_ts))

    touched = reconcile_once(runner=runner)
    refreshed = get_session(session.id)

    assert touched == 0
    assert refreshed is not None
    assert refreshed.status == SessionStatus.IDLE.value
    assert refreshed.attachment_state == "attached"


def test_reconcile_once_does_not_wake_idle_session_on_second_attach_poll(configured_modules, git_repo):
    from app.models.session import SessionStatus
    from app.monitoring import reconciler
    from app.services.sessions import create_managed_session, get_session, update_status

    class TwoPassAttachRunner(RecordingRunner):
        def __init__(self, repo_path: str, *, session_exists: bool = True) -> None:
            super().__init__(repo_path, session_exists=session_exists)
            self._capture_count = 0

        def is_session_attached(self, session_name: str) -> bool:
            self.calls.append(("is_session_attached", session_name))
            return True

        def capture_pane(self, session_name: str, tail: int = 200) -> list[str]:
            self.calls.append(("capture_pane", session_name, tail))
            self._capture_count += 1
            if self._capture_count == 1:
                return ["pane output after attach repaint"]
            return ["pane output after attach repaint", "prompt refreshed after attach"]

    runner = TwoPassAttachRunner(str(git_repo), session_exists=True)

    session = create_managed_session(
        name="attach-second-pass-session",
        repo_path=str(git_repo),
        profile="read-only",
        prompt=None,
        approval_policy="on-request",
        create_worktree_for_writes=False,
        auto_init_git=False,
        launch=True,
        runner=runner,
    )
    update_status(session.id, SessionStatus.IDLE, "Idle for 999s")
    old_ts = (datetime.now(UTC) - timedelta(seconds=900)).timestamp()
    os.utime(session.log_path, (old_ts, old_ts))

    touched = reconciler.reconcile_once(runner=runner)
    refreshed = get_session(session.id)
    assert touched == 0
    assert refreshed is not None
    assert refreshed.status == SessionStatus.IDLE.value
    assert refreshed.output_observed_at is None

    touched = reconciler.reconcile_once(runner=runner)
    refreshed = get_session(session.id)

    assert touched == 0
    assert refreshed is not None
    assert refreshed.status == SessionStatus.IDLE.value
    assert refreshed.output_observed_at is None


def test_remote_runner_round_trip_for_session_creation(configured_modules, monkeypatch, tmp_path):
    from app.runner.client import RemoteRunnerClient
    from app.runner.server import create_app
    from app.services.sessions import create_managed_session

    app = create_app(api_key="secret")
    client = TestClient(app)
    _bridge_urlopen(monkeypatch, client, "http://runner")

    folder = tmp_path / "remote-folder"
    folder.mkdir()
    (folder / "README.md").write_text("hello\n", encoding="utf-8")

    runner = RemoteRunnerClient("http://runner", api_key="secret")
    session = create_managed_session(
        name="remote-runner-session",
        repo_path=str(folder),
        profile="safe-edit",
        prompt=None,
        approval_policy="on-request",
        create_worktree_for_writes=True,
        auto_init_git=True,
        launch=False,
        runner=runner,
    )

    assert session.repo_path == str(folder.resolve())
    assert session.worktree_path is not None
    assert Path(session.worktree_path).exists()
    assert (folder / ".git").exists()


def test_local_runner_can_append_changelog_entry(configured_modules, tmp_path):
    from app.runner.client import LocalRunnerClient

    folder = tmp_path / "repo"
    folder.mkdir()

    runner = LocalRunnerClient()
    changelog_path = runner.ensure_changelog_entry(str(folder), "vat-fix", "Fix VAT rounding", "2026-03-12T09:00:00Z")
    contents = Path(changelog_path).read_text(encoding="utf-8")

    assert "Fix VAT rounding" in contents
    assert "vat-fix" in contents


def test_local_runner_maps_manager_profiles_to_codex_flags(configured_modules):
    from app.runner.client import LocalRunnerClient

    runner = LocalRunnerClient()

    assert runner.build_codex_launch_command("read-only", None) == "codex --no-alt-screen -s read-only -a on-request"
    assert runner.build_codex_launch_command("safe-edit", None) == "codex --no-alt-screen -s workspace-write -a on-request"


def test_local_runner_can_find_recent_codex_session_from_state_db(configured_modules, tmp_path, monkeypatch):
    from app.runner.client import LocalRunnerClient

    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    state_db = codex_home / "state_5.sqlite"
    with sqlite3.connect(state_db) as conn:
        conn.execute(
            """
            CREATE TABLE threads (
              id TEXT PRIMARY KEY,
              rollout_path TEXT NOT NULL,
              created_at INTEGER NOT NULL,
              updated_at INTEGER NOT NULL,
              source TEXT NOT NULL,
              model_provider TEXT NOT NULL,
              cwd TEXT NOT NULL,
              title TEXT NOT NULL,
              sandbox_policy TEXT NOT NULL,
              approval_mode TEXT NOT NULL,
              tokens_used INTEGER NOT NULL DEFAULT 0,
              has_user_event INTEGER NOT NULL DEFAULT 0,
              archived INTEGER NOT NULL DEFAULT 0,
              archived_at INTEGER,
              git_sha TEXT,
              git_branch TEXT,
              git_origin_url TEXT,
              cli_version TEXT NOT NULL DEFAULT '',
              first_user_message TEXT NOT NULL DEFAULT '',
              agent_nickname TEXT,
              agent_role TEXT,
              memory_mode TEXT NOT NULL DEFAULT 'enabled'
            )
            """
        )
        conn.execute(
            """
            INSERT INTO threads (
              id, rollout_path, created_at, updated_at, source, model_provider, cwd, title,
              sandbox_policy, approval_mode, first_user_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "019ce115-d070-7053-b385-870d5e021ea7",
                "rollout.jsonl",
                1773302829,
                1773302835,
                "cli",
                "openai",
                "/repo/service-a",
                "Refactor service layer",
                "workspace-write",
                "on-request",
                "Refactor service layer",
            ),
        )
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    runner = LocalRunnerClient()
    result = runner.find_recent_codex_session(
        "/repo/service-a",
        "Refactor service layer",
        "2026-03-12T08:07:00+00:00",
    )

    assert result == "019ce115-d070-7053-b385-870d5e021ea7"


def test_remote_runner_rejects_invalid_api_key(monkeypatch, tmp_path):
    from app.runner.client import RemoteRunnerClient
    from app.runner.contracts import RunnerError
    from app.runner.server import create_app

    app = create_app(api_key="secret")
    client = TestClient(app)
    _bridge_urlopen(monkeypatch, client, "http://runner")

    folder = tmp_path / "repo"
    folder.mkdir()

    runner = RemoteRunnerClient("http://runner", api_key="wrong")

    try:
        runner.resolve_repo_path(str(folder))
    except RunnerError as exc:
        assert str(exc) == "invalid runner api key"
    else:
        raise AssertionError("expected RunnerError for invalid API key")


def test_get_runner_client_prefers_remote_env(configured_modules, monkeypatch):
    from app.runner.client import RemoteRunnerClient, get_runner_client

    monkeypatch.setenv("RUNNER_BASE_URL", "http://runner.internal:8788")
    monkeypatch.setenv("RUNNER_API_KEY", "secret")

    runner = get_runner_client()

    assert isinstance(runner, RemoteRunnerClient)
    assert runner._base_url == "http://runner.internal:8788"
    assert runner._api_key == "secret"


def test_remote_runner_can_capture_pane(monkeypatch):
    from app.runner.client import RemoteRunnerClient
    from app.runner.server import create_app

    app = create_app(api_key="secret")
    client = TestClient(app)
    _bridge_urlopen(monkeypatch, client, "http://runner")

    runner = RemoteRunnerClient("http://runner", api_key="secret")
    lines = runner.capture_pane("codex-demo", tail=40)

    assert lines == []


def test_remote_runner_can_check_attachment(monkeypatch):
    from app.runner.client import RemoteRunnerClient
    from app.runner.server import create_app

    app = create_app(api_key="secret")
    client = TestClient(app)
    _bridge_urlopen(monkeypatch, client, "http://runner")

    runner = RemoteRunnerClient("http://runner", api_key="secret")
    attached = runner.is_session_attached("codex-demo")

    assert attached is False


def test_remote_runner_can_find_recent_codex_session(monkeypatch, tmp_path):
    from app.runner.client import RemoteRunnerClient
    from app.runner.server import create_app

    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    state_db = codex_home / "state_5.sqlite"
    with sqlite3.connect(state_db) as conn:
        conn.execute(
            """
            CREATE TABLE threads (
              id TEXT PRIMARY KEY,
              rollout_path TEXT NOT NULL,
              created_at INTEGER NOT NULL,
              updated_at INTEGER NOT NULL,
              source TEXT NOT NULL,
              model_provider TEXT NOT NULL,
              cwd TEXT NOT NULL,
              title TEXT NOT NULL,
              sandbox_policy TEXT NOT NULL,
              approval_mode TEXT NOT NULL,
              tokens_used INTEGER NOT NULL DEFAULT 0,
              has_user_event INTEGER NOT NULL DEFAULT 0,
              archived INTEGER NOT NULL DEFAULT 0,
              archived_at INTEGER,
              git_sha TEXT,
              git_branch TEXT,
              git_origin_url TEXT,
              cli_version TEXT NOT NULL DEFAULT '',
              first_user_message TEXT NOT NULL DEFAULT '',
              agent_nickname TEXT,
              agent_role TEXT,
              memory_mode TEXT NOT NULL DEFAULT 'enabled'
            )
            """
        )
        conn.execute(
            """
            INSERT INTO threads (
              id, rollout_path, created_at, updated_at, source, model_provider, cwd, title,
              sandbox_policy, approval_mode, first_user_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "019ce115-d070-7053-b385-870d5e021ea7",
                "rollout.jsonl",
                1773302829,
                1773302835,
                "cli",
                "openai",
                "/repo/service-a",
                "Refactor service layer",
                "workspace-write",
                "on-request",
                "Refactor service layer",
            ),
        )
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    app = create_app(api_key="secret")
    client = TestClient(app)
    _bridge_urlopen(monkeypatch, client, "http://runner")

    runner = RemoteRunnerClient("http://runner", api_key="secret")
    result = runner.find_recent_codex_session(
        "/repo/service-a",
        "Refactor service layer",
        "2026-03-12T08:07:00+00:00",
    )

    assert result == "019ce115-d070-7053-b385-870d5e021ea7"


def test_capture_session_logs_prefers_runner_pane_for_running_sessions(configured_modules):
    from app.services.sessions import capture_session_logs, create_managed_session

    runner = RecordingRunner("/host/repos/service-a")

    session = create_managed_session(
        name="pane-logs",
        repo_path="/container/cannot/see/this",
        profile="safe-edit",
        prompt=None,
        approval_policy="on-request",
        create_worktree_for_writes=False,
        auto_init_git=False,
        launch=True,
        runner=runner,
    )

    lines = capture_session_logs(session.id, tail=50, runner=runner)

    assert lines == ["pane output"]
    assert ("session_exists", session.tmux_session) in runner.calls
    assert ("capture_pane", session.tmux_session, 50) in runner.calls


def test_open_session_keeps_idle_session_idle(configured_modules):
    from app.models.session import SessionStatus
    from app.services.sessions import create_managed_session, get_session, open_session, update_status

    runner = RecordingRunner("/host/repos/service-a")

    session = create_managed_session(
        name="open-idle-session",
        repo_path="/container/cannot/see/this",
        profile="safe-edit",
        prompt=None,
        approval_policy="on-request",
        create_worktree_for_writes=False,
        auto_init_git=False,
        launch=True,
        runner=runner,
    )
    update_status(session.id, SessionStatus.IDLE, "Idle for 999s")

    command = open_session(session.id, runner=runner)
    refreshed = get_session(session.id)

    assert command == f"tmux attach -t {session.tmux_session}"
    assert refreshed is not None
    assert refreshed.status == SessionStatus.IDLE.value

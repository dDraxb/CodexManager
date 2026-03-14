from __future__ import annotations

import io
import os
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
    assert ("session_exists", "codex-lost-managed-session") in runner.calls

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
    assert ("session_exists", "codex-pane-logs") in runner.calls
    assert ("capture_pane", "codex-pane-logs", 50) in runner.calls


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

    assert command == "tmux attach -t codex-open-idle-session"
    assert refreshed is not None
    assert refreshed.status == SessionStatus.IDLE.value

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from app.runner.contracts import RunnerClient, RunnerError
from app.services.shell import ShellError, command_exists
from app.services.tmux import attach_command as tmux_attach_command
from app.services.tmux import capture_pane as tmux_capture_pane
from app.services.tmux import create_session as tmux_create_session
from app.services.tmux import is_session_attached as tmux_is_session_attached
from app.services.tmux import pane_pid as tmux_pane_pid
from app.services.tmux import session_exists as tmux_session_exists
from app.services.tmux import stop_session as tmux_stop_session
from app.services.worktree import changed_files, create_worktree, current_branch, ensure_git_repo


class LocalRunnerClient(RunnerClient):
    def _codex_args_for_profile(self, profile: str) -> list[str]:
        if profile == "read-only":
            return ["codex", "--no-alt-screen", "-s", "read-only", "-a", "on-request"]
        if profile == "safe-edit":
            return ["codex", "--no-alt-screen", "-s", "workspace-write", "-a", "on-request"]
        if profile == "full-agent":
            return ["codex", "--no-alt-screen", "--dangerously-bypass-approvals-and-sandbox"]
        raise RunnerError(f"invalid profile '{profile}'")

    def resolve_repo_path(self, repo_path: str) -> str:
        repo = str(Path(repo_path).expanduser().resolve())
        if not Path(repo).exists():
            raise RunnerError(f"repo path is not accessible: {repo}")
        return repo

    def build_codex_launch_command(self, profile: str, prompt: str | None) -> str:
        configured = os.environ.get("CODEXMGR_CODEX_COMMAND")
        if configured:
            return configured

        if not command_exists("codex"):
            return "printf 'codex not found on PATH. Session created by manager.\\n'; sleep 86400"

        command = self._codex_args_for_profile(profile)
        if prompt:
            command.append(json.dumps(prompt))
        return " ".join(command)

    def ensure_git_repo(self, repo_path: str, auto_init: bool = False) -> None:
        try:
            ensure_git_repo(repo_path, auto_init=auto_init)
        except ShellError as exc:
            raise RunnerError(str(exc)) from exc

    def create_worktree(self, repo_path: str, session_name: str, branch: str, auto_init: bool = False) -> str:
        try:
            return create_worktree(repo_path, session_name, branch, auto_init=auto_init)
        except ShellError as exc:
            raise RunnerError(str(exc)) from exc

    def changed_files(self, repo_path: str, cwd: str | None) -> list[str]:
        try:
            return changed_files(repo_path, cwd)
        except ShellError as exc:
            raise RunnerError(str(exc)) from exc

    def current_branch(self, repo_path: str, cwd: str | None) -> str | None:
        try:
            return current_branch(repo_path, cwd)
        except ShellError as exc:
            raise RunnerError(str(exc)) from exc

    def ensure_changelog_entry(self, repo_path: str, session_name: str, prompt: str | None, timestamp: str) -> str:
        changelog_path = Path(repo_path) / "CHANGELOG.md"
        if not changelog_path.exists():
            changelog_path.write_text("# Changelog\n\n", encoding="utf-8")

        with changelog_path.open("a", encoding="utf-8") as handle:
            handle.write(
                "\n".join(
                    [
                        f"## {timestamp} - {session_name}",
                        "",
                        f"- Prompt: {prompt or '(none provided)'}",
                        "- Changes:",
                        "- Validation:",
                        "",
                    ]
                )
            )
        return str(changelog_path)

    def session_exists(self, session_name: str) -> bool:
        return tmux_session_exists(session_name)

    def create_session(self, session_name: str, cwd: str, log_path: str, launch_cmd: str | None) -> None:
        try:
            tmux_create_session(session_name, cwd, log_path, launch_cmd)
        except (RuntimeError, ShellError) as exc:
            raise RunnerError(str(exc)) from exc

    def stop_session(self, session_name: str) -> None:
        try:
            tmux_stop_session(session_name)
        except ShellError as exc:
            raise RunnerError(str(exc)) from exc

    def attach_command(self, session_name: str) -> str:
        return tmux_attach_command(session_name)

    def pane_pid(self, session_name: str) -> int | None:
        try:
            return tmux_pane_pid(session_name)
        except ShellError as exc:
            raise RunnerError(str(exc)) from exc

    def capture_pane(self, session_name: str, tail: int = 200) -> list[str]:
        try:
            return tmux_capture_pane(session_name, tail)
        except ShellError as exc:
            raise RunnerError(str(exc)) from exc

    def is_session_attached(self, session_name: str) -> bool:
        try:
            return tmux_is_session_attached(session_name)
        except ShellError as exc:
            raise RunnerError(str(exc)) from exc


class RemoteRunnerClient(RunnerClient):
    def __init__(self, base_url: str, api_key: str | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key

    def resolve_repo_path(self, repo_path: str) -> str:
        payload = self._post("/resolve-repo-path", {"repo_path": repo_path})
        return str(payload["repo_path"])

    def build_codex_launch_command(self, profile: str, prompt: str | None) -> str:
        payload = self._post("/build-codex-launch-command", {"profile": profile, "prompt": prompt})
        return str(payload["launch_command"])

    def ensure_git_repo(self, repo_path: str, auto_init: bool = False) -> None:
        self._post("/ensure-git-repo", {"repo_path": repo_path, "auto_init": auto_init})

    def create_worktree(self, repo_path: str, session_name: str, branch: str, auto_init: bool = False) -> str:
        payload = self._post(
            "/create-worktree",
            {
                "repo_path": repo_path,
                "session_name": session_name,
                "branch": branch,
                "auto_init": auto_init,
            },
        )
        return str(payload["worktree_path"])

    def changed_files(self, repo_path: str, cwd: str | None) -> list[str]:
        payload = self._post("/changed-files", {"repo_path": repo_path, "cwd": cwd})
        return [str(item) for item in payload["files"]]

    def current_branch(self, repo_path: str, cwd: str | None) -> str | None:
        payload = self._post("/current-branch", {"repo_path": repo_path, "cwd": cwd})
        branch = payload["branch"]
        return str(branch) if branch is not None else None

    def ensure_changelog_entry(self, repo_path: str, session_name: str, prompt: str | None, timestamp: str) -> str:
        payload = self._post(
            "/ensure-changelog-entry",
            {
                "repo_path": repo_path,
                "session_name": session_name,
                "prompt": prompt,
                "timestamp": timestamp,
            },
        )
        return str(payload["changelog_path"])

    def session_exists(self, session_name: str) -> bool:
        payload = self._post("/tmux/session-exists", {"session_name": session_name})
        return bool(payload["exists"])

    def create_session(self, session_name: str, cwd: str, log_path: str, launch_cmd: str | None) -> None:
        self._post(
            "/tmux/create-session",
            {
                "session_name": session_name,
                "cwd": cwd,
                "log_path": log_path,
                "launch_cmd": launch_cmd,
            },
        )

    def stop_session(self, session_name: str) -> None:
        self._post("/tmux/stop-session", {"session_name": session_name})

    def attach_command(self, session_name: str) -> str:
        payload = self._post("/tmux/attach-command", {"session_name": session_name})
        return str(payload["command"])

    def pane_pid(self, session_name: str) -> int | None:
        payload = self._post("/tmux/pane-pid", {"session_name": session_name})
        value = payload["pane_pid"]
        return int(value) if value is not None else None

    def capture_pane(self, session_name: str, tail: int = 200) -> list[str]:
        payload = self._post("/tmux/capture-pane", {"session_name": session_name, "tail": tail})
        return [str(line) for line in payload["lines"]]

    def is_session_attached(self, session_name: str) -> bool:
        payload = self._post("/tmux/is-attached", {"session_name": session_name})
        return bool(payload["attached"])

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=body, method="POST")
        request.add_header("Content-Type", "application/json")
        if self._api_key:
            request.add_header("X-Runner-Api-Key", self._api_key)

        try:
            with urllib.request.urlopen(request) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace").strip()
            if detail:
                try:
                    payload = json.loads(detail)
                except json.JSONDecodeError:
                    pass
                else:
                    message = payload.get("detail")
                    if isinstance(message, str) and message:
                        detail = message
            raise RunnerError(detail or f"runner request failed with status {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise RunnerError(f"runner request failed: {exc.reason}") from exc

        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise RunnerError("runner returned invalid JSON") from exc


def get_runner_client() -> RunnerClient:
    base_url = os.environ.get("RUNNER_BASE_URL") or os.environ.get("CODEXMGR_RUNNER_BASE_URL")
    if base_url:
        api_key = os.environ.get("RUNNER_API_KEY") or os.environ.get("CODEXMGR_RUNNER_API_KEY")
        return RemoteRunnerClient(base_url, api_key=api_key)
    return LocalRunnerClient()

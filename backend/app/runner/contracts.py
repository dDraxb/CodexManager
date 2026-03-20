from __future__ import annotations

from typing import Protocol


class RunnerError(RuntimeError):
    pass


class RunnerClient(Protocol):
    def resolve_repo_path(self, repo_path: str) -> str:
        """Validate and normalize a repository path in the execution environment."""

    def build_codex_launch_command(self, profile: str, prompt: str | None) -> str:
        """Build the command used to launch Codex in the execution environment."""

    def ensure_git_repo(self, repo_path: str, auto_init: bool = False) -> None:
        """Ensure the given path is a usable git repository."""

    def create_worktree(self, repo_path: str, session_name: str, branch: str, auto_init: bool = False) -> str:
        """Create and return a writable worktree path for a session."""

    def changed_files(self, repo_path: str, cwd: str | None) -> list[str]:
        """Return changed files visible from the execution environment."""

    def current_branch(self, repo_path: str, cwd: str | None) -> str | None:
        """Return the current checked-out branch, if any."""

    def ensure_changelog_entry(self, repo_path: str, session_name: str, prompt: str | None, timestamp: str) -> str:
        """Ensure CHANGELOG.md exists and append a new work entry template."""

    def find_recent_codex_session(self, cwd: str, prompt: str | None, since: str | None) -> str | None:
        """Return a recent Codex-native session id for this cwd when one can be identified safely."""

    def list_codex_threads(self, cwd: str | None, query: str | None, limit: int = 20) -> list[dict]:
        """Return recent Codex thread metadata."""

    def list_resume_candidates(self, thread_id: str | None, cwd: str | None, prompt: str | None, limit: int = 12) -> list[dict]:
        """Return chooser candidates for a session resume flow."""

    def session_exists(self, session_name: str) -> bool:
        """Return whether a tmux session exists."""

    def create_session(self, session_name: str, cwd: str, log_path: str, launch_cmd: str | None) -> None:
        """Start a tmux session."""

    def stop_session(self, session_name: str) -> None:
        """Stop a tmux session if it exists."""

    def attach_command(self, session_name: str) -> str:
        """Return the user-facing attach command for a tmux session."""

    def pane_pid(self, session_name: str) -> int | None:
        """Return the pid of the tmux pane, if available."""

    def capture_pane(self, session_name: str, tail: int = 200) -> list[str]:
        """Return recent rendered pane lines for a tmux session."""

    def is_session_attached(self, session_name: str) -> bool:
        """Return whether a tmux client is attached to the session."""

from __future__ import annotations

from typing import Protocol


class RunnerError(RuntimeError):
    pass


class RunnerClient(Protocol):
    def resolve_repo_path(self, repo_path: str | None) -> str:
        """Validate and normalize a working directory path in the execution environment."""

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

    def detect_validation_recipe(self, repo_path: str) -> dict | None:
        """Return validation recipe metadata when the working directory is recognized."""

    def apply_validation_preset(self, repo_path: str, preset_id: str) -> str:
        """Write repo-local validation config that references a manager preset and return the file path."""

    def materialize_validation_recipe(self, repo_path: str, recipe_json: str) -> str:
        """Write repo-local validation config for the effective recipe and return the file path."""

    def inspect_codex_environment(self, repo_path: str | None) -> dict:
        """Return global and workspace Codex environment metadata from the execution environment."""

    def create_codex_skill(self, scope: str, name: str, summary: str, repo_path: str | None = None) -> dict:
        """Create a global or workspace Codex skill scaffold and return its metadata."""

    def read_codex_config(self, scope: str, repo_path: str | None = None) -> dict:
        """Read global or workspace Codex config content from the execution environment."""

    def write_codex_config(self, scope: str, content: str, repo_path: str | None = None) -> dict:
        """Write global or workspace Codex config content and return saved metadata."""

    def restore_codex_config(self, scope: str, backup_path: str, repo_path: str | None = None) -> dict:
        """Restore a Codex config file from a saved backup."""

    def read_codex_rules(self, scope: str, repo_path: str | None = None) -> dict:
        """Read global or workspace Codex instruction rules."""

    def write_codex_rules(self, scope: str, content: str, repo_path: str | None = None) -> dict:
        """Write global or workspace Codex instruction rules."""

    def restore_codex_rules(self, scope: str, backup_path: str, repo_path: str | None = None) -> dict:
        """Restore Codex instruction rules from a saved backup."""

    def list_codex_agents(self) -> list[dict]:
        """List configured Codex agents from the execution environment."""

    def create_codex_agent(self, name: str, summary: str = "") -> dict:
        """Create a Codex agent scaffold and register it in global config."""

    def list_codex_mcp_servers(self, scope: str, repo_path: str | None = None) -> dict:
        """List MCP server entries from Codex config."""

    def create_codex_mcp_server(
        self,
        scope: str,
        name: str,
        command: str,
        args: list[str] | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        repo_path: str | None = None,
    ) -> dict:
        """Create a Codex MCP server entry."""

    def delete_codex_mcp_server(self, scope: str, name: str, repo_path: str | None = None) -> dict:
        """Delete a Codex MCP server entry."""

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

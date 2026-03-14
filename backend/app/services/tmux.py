from __future__ import annotations

import os
import shlex
import subprocess

from app.services.shell import command_exists, run


class TmuxUnavailableError(RuntimeError):
    pass



def _require_tmux() -> None:
    if not command_exists("tmux"):
        raise TmuxUnavailableError("tmux is not installed or not on PATH")


def session_exists(session_name: str) -> bool:
    if not command_exists("tmux"):
        return False
    proc = subprocess.run(
        ["tmux", "has-session", "-t", session_name],
        text=True,
        capture_output=True,
        check=False,
    )
    return proc.returncode == 0


def create_session(session_name: str, cwd: str, log_path: str, launch_cmd: str | None) -> None:
    _require_tmux()
    if session_exists(session_name):
        raise RuntimeError(f"tmux session already exists: {session_name}")

    command = launch_cmd or os.environ.get("SHELL", "/bin/zsh")
    run(["tmux", "new-session", "-d", "-s", session_name, "-c", cwd, command])
    # Capture pane output without breaking interactive TTY behavior for Codex.
    run(["tmux", "pipe-pane", "-o", "-t", session_name, f"cat >> {shlex.quote(log_path)}"])


def stop_session(session_name: str) -> None:
    if not session_exists(session_name):
        return
    run(["tmux", "kill-session", "-t", session_name])


def attach_command(session_name: str) -> str:
    return f"tmux attach -t {shlex.quote(session_name)}"


def pane_pid(session_name: str) -> int | None:
    if not session_exists(session_name):
        return None
    proc = run(["tmux", "display-message", "-p", "-t", session_name, "#{pane_pid}"])
    raw = proc.stdout.strip()
    return int(raw) if raw.isdigit() else None


def capture_pane(session_name: str, tail: int = 200) -> list[str]:
    if not session_exists(session_name):
        return []
    proc = run(["tmux", "capture-pane", "-p", "-t", session_name, "-S", f"-{max(1, tail)}"])
    return proc.stdout.splitlines()


def is_session_attached(session_name: str) -> bool:
    if not session_exists(session_name):
        return False
    proc = run(["tmux", "display-message", "-p", "-t", session_name, "#{session_attached}"])
    return proc.stdout.strip() == "1"

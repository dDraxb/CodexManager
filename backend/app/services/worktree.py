from __future__ import annotations

from pathlib import Path

from app.core.constants import WORKTREES_DIR
from app.services.shell import ShellError, run


def _is_git_repo(repo_path: str) -> bool:
    try:
        run(["git", "-C", repo_path, "rev-parse", "--is-inside-work-tree"])
    except ShellError:
        return False
    return True


def _has_commits(repo_path: str) -> bool:
    try:
        run(["git", "-C", repo_path, "rev-parse", "--verify", "HEAD"])
    except ShellError:
        return False
    return True


def _bootstrap_git_repo(repo_path: str) -> None:
    run(["git", "-C", repo_path, "init"])
    try:
        run(["git", "-C", repo_path, "config", "user.email"])
    except ShellError:
        run(["git", "-C", repo_path, "config", "user.email", "codexmgr@local"])
    try:
        run(["git", "-C", repo_path, "config", "user.name"])
    except ShellError:
        run(["git", "-C", repo_path, "config", "user.name", "Codex Session Manager"])
    run(["git", "-C", repo_path, "commit", "--allow-empty", "-m", "Initialize repository for codexmgr"])


def ensure_git_repo(repo_path: str, auto_init: bool = False) -> None:
    if _is_git_repo(repo_path):
        if not _has_commits(repo_path) and auto_init:
            _bootstrap_git_repo(repo_path)
        return
    if not auto_init:
        raise ShellError(f"path is not a git repository: {repo_path}")
    _bootstrap_git_repo(repo_path)


def create_worktree(repo_path: str, session_name: str, branch: str, auto_init: bool = False) -> str:
    ensure_git_repo(repo_path, auto_init=auto_init)
    worktree_path = WORKTREES_DIR / session_name
    if worktree_path.exists():
        raise ShellError(f"worktree path already exists: {worktree_path}")

    run(["git", "-C", repo_path, "worktree", "add", "-b", branch, str(worktree_path)])
    return str(worktree_path)


def remove_worktree(repo_path: str, worktree_path: str) -> None:
    ensure_git_repo(repo_path)
    run(["git", "-C", repo_path, "worktree", "remove", "--force", worktree_path])


def changed_files(repo_path: str, cwd: str | None) -> list[str]:
    target = cwd or repo_path
    proc = run(["git", "-C", target, "status", "--porcelain"])
    out = proc.stdout.strip()
    if not out:
        return []
    files: list[str] = []
    for line in out.splitlines():
        if len(line) < 4:
            continue
        files.append(line[3:])
    return files


def current_branch(repo_path: str, cwd: str | None) -> str | None:
    target = cwd or repo_path
    proc = run(["git", "-C", target, "branch", "--show-current"])
    branch = proc.stdout.strip()
    return branch or None

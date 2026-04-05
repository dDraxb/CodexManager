from __future__ import annotations

from pathlib import Path

from app.services.codex_environment import codex_home_path
from app.services.file_backups import backup_file, list_backups, restore_backup


class CodexRulesError(RuntimeError):
    pass


def _rules_path(scope: str, repo_path: str | None) -> Path:
    if scope == "global":
        return codex_home_path() / "AGENTS.md"
    if scope == "workspace":
        if not repo_path:
            raise CodexRulesError("workspace rules require a repo path")
        return Path(repo_path).expanduser() / "AGENTS.md"
    raise CodexRulesError(f"invalid rules scope '{scope}'")


def read_codex_rules(*, scope: str, repo_path: str | None = None) -> dict:
    path = _rules_path(scope, repo_path)
    exists = path.exists()
    return {
        "scope": scope,
        "path": str(path),
        "exists": exists,
        "content": path.read_text(encoding="utf-8") if exists else "",
        "backups": list_backups(path),
    }


def write_codex_rules(*, scope: str, content: str, repo_path: str | None = None) -> dict:
    path = _rules_path(scope, repo_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    backup_path = backup_file(path)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")
    return {
        "scope": scope,
        "path": str(path),
        "backupPath": backup_path,
    }


def restore_codex_rules(*, scope: str, backup_path: str, repo_path: str | None = None) -> dict:
    path = _rules_path(scope, repo_path)
    try:
        restored = restore_backup(path, backup_path)
    except FileNotFoundError as exc:
        raise CodexRulesError(str(exc)) from exc
    return {
        "scope": scope,
        **restored,
    }

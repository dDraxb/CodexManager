from __future__ import annotations

from difflib import unified_diff
from pathlib import Path
import tomllib

from app.services.codex_environment import codex_home_path
from app.services.file_backups import backup_file, list_backups, restore_backup


class CodexConfigError(RuntimeError):
    pass


def _config_path(scope: str, repo_path: str | None) -> Path:
    if scope == "global":
        return codex_home_path() / "config.toml"
    if scope == "workspace":
        if not repo_path:
            raise CodexConfigError("workspace config requires a repo path")
        return Path(repo_path).expanduser() / ".codex" / "config.toml"
    raise CodexConfigError(f"invalid config scope '{scope}'")


def read_codex_config(*, scope: str, repo_path: str | None = None) -> dict:
    path = _config_path(scope, repo_path)
    exists = path.exists()
    return {
        "scope": scope,
        "path": str(path),
        "exists": exists,
        "content": path.read_text(encoding="utf-8") if exists else "",
        "backups": list_backups(path),
    }


def preview_codex_config(*, scope: str, content: str, repo_path: str | None = None) -> dict:
    path = _config_path(scope, repo_path)
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    try:
        tomllib.loads(content or "")
    except tomllib.TOMLDecodeError as exc:
        raise CodexConfigError(f"invalid TOML: {exc}") from exc
    diff = list(
        unified_diff(
            current.splitlines(),
            content.splitlines(),
            fromfile=f"{path.name} (current)",
            tofile=f"{path.name} (proposed)",
            lineterm="",
        )
    )
    return {
        "scope": scope,
        "path": str(path),
        "valid": True,
        "diff": diff,
    }


def write_codex_config(*, scope: str, content: str, repo_path: str | None = None) -> dict:
    path = _config_path(scope, repo_path)
    try:
        tomllib.loads(content or "")
    except tomllib.TOMLDecodeError as exc:
        raise CodexConfigError(f"invalid TOML: {exc}") from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    backup_path = backup_file(path)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")
    return {
        "scope": scope,
        "path": str(path),
        "backupPath": backup_path,
    }


def restore_codex_config(*, scope: str, backup_path: str, repo_path: str | None = None) -> dict:
    path = _config_path(scope, repo_path)
    try:
        restored = restore_backup(path, backup_path)
    except FileNotFoundError as exc:
        raise CodexConfigError(str(exc)) from exc
    return {
        "scope": scope,
        **restored,
    }

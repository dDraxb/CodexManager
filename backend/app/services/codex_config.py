from __future__ import annotations

from pathlib import Path

from app.services.codex_environment import codex_home_path


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
    }


def write_codex_config(*, scope: str, content: str, repo_path: str | None = None) -> dict:
    path = _config_path(scope, repo_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    backup_path = None
    if path.exists():
        backup_path = path.with_suffix(path.suffix + ".bak")
        backup_path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    path.write_text(content.rstrip() + "\n", encoding="utf-8")
    return {
        "scope": scope,
        "path": str(path),
        "backupPath": str(backup_path) if backup_path else None,
    }

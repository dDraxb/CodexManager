from __future__ import annotations

import re
import shutil
from pathlib import Path

from app.services.codex_environment import codex_home_path
from app.services.file_backups import backup_file, list_backups, restore_backup

PROMPT_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")


class CodexPromptError(RuntimeError):
    pass


def _prompt_root(scope: str, repo_path: str | None) -> Path:
    if scope == "global":
        return codex_home_path() / "prompts"
    if scope == "workspace":
        if not repo_path:
            raise CodexPromptError("workspace prompts require a repo path")
        return Path(repo_path).expanduser() / ".codex" / "prompts"
    raise CodexPromptError(f"invalid prompt scope '{scope}'")


def _prompt_path(scope: str, name: str, repo_path: str | None) -> Path:
    normalized_name = name.strip().lower()
    if not PROMPT_NAME_PATTERN.fullmatch(normalized_name):
        raise CodexPromptError("prompt name must use lowercase letters, numbers, dash, or underscore")
    return _prompt_root(scope, repo_path) / f"{normalized_name}.md"


def list_codex_prompts(*, scope: str, repo_path: str | None = None) -> list[dict]:
    root = _prompt_root(scope, repo_path)
    if not root.exists() or not root.is_dir():
        return []
    prompts: list[dict] = []
    for child in sorted(root.iterdir(), key=lambda item: item.name.lower()):
        if not child.is_file() or child.suffix.lower() not in {".md", ".txt"}:
            continue
        prompts.append(
            {
                "scope": scope,
                "name": child.stem,
                "path": str(child),
            }
        )
    return prompts


def create_codex_prompt(*, scope: str, name: str, content: str = "", repo_path: str | None = None) -> dict:
    path = _prompt_path(scope, name, repo_path)
    if path.exists():
        raise CodexPromptError(f"prompt '{path.stem}' already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    initial = content.strip() or f"# {path.stem.replace('-', ' ').replace('_', ' ').title()}\n\nDescribe how this prompt should be used.\n"
    path.write_text(initial.rstrip() + "\n", encoding="utf-8")
    return {
        "scope": scope,
        "name": path.stem,
        "path": str(path),
    }


def read_codex_prompt(*, scope: str, name: str, repo_path: str | None = None) -> dict:
    path = _prompt_path(scope, name, repo_path)
    exists = path.exists()
    return {
        "scope": scope,
        "name": path.stem,
        "path": str(path),
        "exists": exists,
        "content": path.read_text(encoding="utf-8") if exists else "",
        "backups": list_backups(path),
    }


def write_codex_prompt(*, scope: str, name: str, content: str, repo_path: str | None = None) -> dict:
    path = _prompt_path(scope, name, repo_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    backup_path = backup_file(path)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")
    return {
        "scope": scope,
        "name": path.stem,
        "path": str(path),
        "backupPath": backup_path,
    }


def restore_codex_prompt(*, scope: str, name: str, backup_path: str, repo_path: str | None = None) -> dict:
    path = _prompt_path(scope, name, repo_path)
    try:
        restored = restore_backup(path, backup_path)
    except FileNotFoundError as exc:
        raise CodexPromptError(str(exc)) from exc
    return {
        "scope": scope,
        "name": path.stem,
        "path": str(path),
        **restored,
    }


def delete_codex_prompt(*, scope: str, name: str, repo_path: str | None = None) -> dict:
    path = _prompt_path(scope, name, repo_path)
    if not path.exists():
        raise CodexPromptError(f"prompt '{path.stem}' does not exist")
    archive_root = path.parent / ".codexmgr-deleted-prompts"
    archive_root.mkdir(parents=True, exist_ok=True)
    archived_path = archive_root / path.name
    if archived_path.exists():
        archived_path.unlink()
    shutil.move(str(path), str(archived_path))
    return {
        "scope": scope,
        "name": path.stem,
        "path": str(path),
        "archivedPath": str(archived_path),
    }

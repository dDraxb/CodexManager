from __future__ import annotations

import re
import shutil
from pathlib import Path

from app.services.codex_environment import codex_home_path
from app.services.file_backups import backup_file, list_backups, restore_backup

SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")


class CodexSkillError(RuntimeError):
    pass


def _skill_root(scope: str, repo_path: str | None) -> Path:
    if scope == "global":
        return codex_home_path() / "skills"
    if scope == "workspace":
        if not repo_path:
            raise CodexSkillError("workspace skills require a repo path")
        return Path(repo_path).expanduser() / ".codex" / "skills"
    raise CodexSkillError(f"invalid skill scope '{scope}'")


def _skill_template(name: str, summary: str) -> str:
    title = name.replace("-", " ").replace("_", " ").title()
    summary_line = summary.strip() or f"Local skill for {title}."
    return (
        f"# {title}\n\n"
        f"{summary_line}\n\n"
        "## Purpose\n"
        "- Describe when this skill should be used.\n\n"
        "## Workflow\n"
        "- Add the steps Codex should follow.\n\n"
        "## Constraints\n"
        "- Add repo-specific guardrails or requirements.\n"
    )


def create_codex_skill(*, scope: str, name: str, summary: str = "", repo_path: str | None = None) -> dict:
    normalized_name = name.strip().lower()
    if not SKILL_NAME_PATTERN.fullmatch(normalized_name):
        raise CodexSkillError("skill name must use lowercase letters, numbers, dash, or underscore")
    root = _skill_root(scope, repo_path)
    skill_dir = root / normalized_name
    skill_file = skill_dir / "SKILL.md"
    if skill_dir.exists():
        raise CodexSkillError(f"skill '{normalized_name}' already exists")
    skill_dir.mkdir(parents=True, exist_ok=False)
    skill_file.write_text(_skill_template(normalized_name, summary), encoding="utf-8")
    return {
        "scope": scope,
        "name": normalized_name,
        "path": str(skill_dir),
        "skillFile": str(skill_file),
    }


def read_codex_skill(*, scope: str, name: str, repo_path: str | None = None) -> dict:
    normalized_name = name.strip().lower()
    root = _skill_root(scope, repo_path)
    skill_dir = root / normalized_name
    skill_file = skill_dir / "SKILL.md"
    exists = skill_file.exists()
    return {
        "scope": scope,
        "name": normalized_name,
        "path": str(skill_dir),
        "skillFile": str(skill_file),
        "exists": exists,
        "content": skill_file.read_text(encoding="utf-8") if exists else "",
        "backups": list_backups(skill_file),
    }


def write_codex_skill(*, scope: str, name: str, content: str, repo_path: str | None = None) -> dict:
    normalized_name = name.strip().lower()
    root = _skill_root(scope, repo_path)
    skill_dir = root / normalized_name
    skill_file = skill_dir / "SKILL.md"
    skill_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_file(skill_file)
    skill_file.write_text(content.rstrip() + "\n", encoding="utf-8")
    return {
        "scope": scope,
        "name": normalized_name,
        "path": str(skill_dir),
        "skillFile": str(skill_file),
        "backupPath": backup_path,
    }


def restore_codex_skill(*, scope: str, name: str, backup_path: str, repo_path: str | None = None) -> dict:
    normalized_name = name.strip().lower()
    root = _skill_root(scope, repo_path)
    skill_dir = root / normalized_name
    skill_file = skill_dir / "SKILL.md"
    try:
        restored = restore_backup(skill_file, backup_path)
    except FileNotFoundError as exc:
        raise CodexSkillError(str(exc)) from exc
    return {
        "scope": scope,
        "name": normalized_name,
        "path": str(skill_dir),
        "skillFile": str(skill_file),
        **restored,
    }


def delete_codex_skill(*, scope: str, name: str, repo_path: str | None = None) -> dict:
    normalized_name = name.strip().lower()
    root = _skill_root(scope, repo_path)
    skill_dir = root / normalized_name
    if not skill_dir.exists():
        raise CodexSkillError(f"skill '{normalized_name}' does not exist")
    backup_root = skill_dir.parent / ".codexmgr-deleted-skills"
    backup_root.mkdir(parents=True, exist_ok=True)
    archived_path = backup_root / normalized_name
    if archived_path.exists():
        shutil.rmtree(archived_path)
    shutil.move(str(skill_dir), str(archived_path))
    return {
        "scope": scope,
        "name": normalized_name,
        "path": str(skill_dir),
        "archivedPath": str(archived_path),
    }

from __future__ import annotations

import re
from pathlib import Path

from app.services.codex_environment import codex_home_path

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

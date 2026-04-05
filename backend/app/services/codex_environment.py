from __future__ import annotations

import os
from pathlib import Path

def codex_home_path() -> Path:
    raw = os.environ.get("CODEX_HOME")
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".codex"


def _skill_entries(root: Path) -> list[dict]:
    if not root.exists() or not root.is_dir():
        return []
    entries: list[dict] = []
    for child in sorted(root.iterdir(), key=lambda item: item.name.lower()):
        skill_file = child / "SKILL.md"
        if not child.is_dir() or not skill_file.exists():
            continue
        entries.append(
            {
                "name": child.name,
                "path": str(child),
                "skillFile": str(skill_file),
            }
        )
    return entries


def _prompt_entries(root: Path) -> list[dict]:
    if not root.exists() or not root.is_dir():
        return []
    entries: list[dict] = []
    for child in sorted(root.iterdir(), key=lambda item: item.name.lower()):
        if not child.is_file() or child.suffix.lower() not in {".md", ".txt"}:
            continue
        entries.append(
            {
                "name": child.stem,
                "path": str(child),
            }
        )
    return entries


def inspect_codex_environment(repo_path: str | None = None) -> dict:
    from app.services.codex_agents import list_codex_agents

    codex_home = codex_home_path()
    global_config = codex_home / "config.toml"
    global_skills_root = codex_home / "skills"
    global_prompts_root = codex_home / "prompts"
    workspace_root = Path(repo_path).expanduser() if repo_path else None
    workspace_config = workspace_root / ".codex" / "config.toml" if workspace_root else None
    workspace_skills_root = workspace_root / ".codex" / "skills" if workspace_root else None
    workspace_prompts_root = workspace_root / ".codex" / "prompts" if workspace_root else None
    return {
        "codexHome": str(codex_home),
        "globalConfig": {
            "path": str(global_config),
            "exists": global_config.exists(),
        },
        "workspaceConfig": {
            "path": str(workspace_config) if workspace_config else None,
            "exists": workspace_config.exists() if workspace_config else False,
        },
        "globalSkills": _skill_entries(global_skills_root),
        "workspaceSkills": _skill_entries(workspace_skills_root) if workspace_skills_root else [],
        "globalPrompts": _prompt_entries(global_prompts_root),
        "workspacePrompts": _prompt_entries(workspace_prompts_root) if workspace_prompts_root else [],
        "globalAgents": list_codex_agents(),
    }

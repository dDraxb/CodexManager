from __future__ import annotations

from pathlib import Path

from app.services.codex_agents import CodexAgentError, list_codex_agents
from app.services.file_backups import backup_file, list_backups, restore_backup


class CodexAgentConfigError(RuntimeError):
    pass


def _agent_config_path(name: str) -> Path:
    normalized = name.strip()
    if not normalized:
        raise CodexAgentConfigError("agent name is required")
    for agent in list_codex_agents():
        if agent["name"] == normalized and agent.get("configFile"):
            return Path(agent["configFile"]).expanduser()
    raise CodexAgentConfigError(f"agent '{normalized}' is not configured")


def read_codex_agent_config(name: str) -> dict:
    try:
        path = _agent_config_path(name)
    except CodexAgentError as exc:
        raise CodexAgentConfigError(str(exc)) from exc
    exists = path.exists()
    return {
        "name": name.strip(),
        "path": str(path),
        "exists": exists,
        "content": path.read_text(encoding="utf-8") if exists else "",
        "backups": list_backups(path),
    }


def write_codex_agent_config(name: str, content: str) -> dict:
    path = _agent_config_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    backup_path = backup_file(path)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")
    return {
        "name": name.strip(),
        "path": str(path),
        "backupPath": backup_path,
    }


def restore_codex_agent_config(name: str, backup_path: str) -> dict:
    path = _agent_config_path(name)
    try:
        restored = restore_backup(path, backup_path)
    except FileNotFoundError as exc:
        raise CodexAgentConfigError(str(exc)) from exc
    return {
        "name": name.strip(),
        **restored,
    }

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from app.services.codex_config import read_codex_config
from app.services.codex_environment import codex_home_path

AGENT_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")


class CodexAgentError(RuntimeError):
    pass


def list_codex_agents() -> list[dict]:
    config = read_codex_config(scope="global")
    if not config["exists"] or not config["content"].strip():
        return []
    try:
        payload = tomllib.loads(config["content"])
    except tomllib.TOMLDecodeError:
        return []
    agents = payload.get("agents")
    if not isinstance(agents, dict):
        return []
    rows: list[dict] = []
    for name, entry in sorted(agents.items(), key=lambda item: str(item[0]).lower()):
        if not isinstance(entry, dict):
            continue
        rows.append(
            {
                "name": str(name),
                "configFile": str(entry.get("config_file") or "").strip() or None,
            }
        )
    return rows


def _agent_template(name: str, summary: str) -> str:
    title = name.replace("-", " ").replace("_", " ").title()
    description = summary.strip() or f"{title} agent scaffold."
    return (
        f"# {title}\n\n"
        f'description = "{description}"\n'
        'model = "gpt-5.4"\n'
        'approval_policy = "on-request"\n'
    )


def create_codex_agent(*, name: str, summary: str = "") -> dict:
    normalized_name = name.strip().lower()
    if not AGENT_NAME_PATTERN.fullmatch(normalized_name):
        raise CodexAgentError("agent name must use lowercase letters, numbers, dash, or underscore")

    existing = {row["name"] for row in list_codex_agents()}
    if normalized_name in existing:
        raise CodexAgentError(f"agent '{normalized_name}' already exists")

    codex_home = codex_home_path()
    agents_dir = codex_home / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    agent_file = agents_dir / f"{normalized_name}.toml"
    if agent_file.exists():
        raise CodexAgentError(f"agent config '{agent_file.name}' already exists")
    agent_file.write_text(_agent_template(normalized_name, summary), encoding="utf-8")

    config_path = codex_home / "config.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if config_path.exists():
        original = config_path.read_text(encoding="utf-8")
        backup_path = config_path.with_suffix(config_path.suffix + ".bak")
        backup_path.write_text(original, encoding="utf-8")
    else:
        original = ""
        backup_path = None

    appended = (
        ("\n" if original and not original.endswith("\n") else "")
        + f'\n[agents."{normalized_name}"]\n'
        + f'config_file = "{agent_file}"\n'
    )
    config_path.write_text(original + appended, encoding="utf-8")
    return {
        "name": normalized_name,
        "configFile": str(agent_file),
        "configPath": str(config_path),
        "backupPath": str(backup_path) if backup_path else None,
    }

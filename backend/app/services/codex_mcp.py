from __future__ import annotations

import json
import tomllib
from pathlib import Path

from app.services.codex_config import CodexConfigError, _config_path
from app.services.file_backups import backup_file


class CodexMcpError(RuntimeError):
    pass


def _render_mcp_block(normalized_name: str, normalized_command: str, args: list[str] | None, cwd: str | None, env: dict[str, str] | None) -> str:
    block_lines = [
        f'[mcp_servers."{normalized_name}"]',
        f'command = {json.dumps(normalized_command)}',
    ]
    normalized_args = [str(item) for item in (args or []) if str(item).strip()]
    if normalized_args:
        block_lines.append(f"args = {json.dumps(normalized_args)}")
    if cwd and cwd.strip():
        block_lines.append(f"cwd = {json.dumps(cwd.strip())}")
    normalized_env = {str(key): str(value) for key, value in (env or {}).items() if str(key).strip()}
    if normalized_env:
        block_lines.append("[mcp_servers." + json.dumps(normalized_name) + ".env]")
        for key, value in normalized_env.items():
            block_lines.append(f"{key} = {json.dumps(value)}")
    return "\n".join(block_lines)


def _remove_mcp_block(content: str, normalized_name: str) -> str:
    target_prefix = f'[mcp_servers."{normalized_name}"'
    lines = content.splitlines()
    kept: list[str] = []
    skipping = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if stripped.startswith(target_prefix):
                skipping = True
                continue
            if skipping:
                skipping = False
        if not skipping:
            kept.append(line)

    return "\n".join(kept).rstrip() + "\n"


def list_codex_mcp_servers(*, scope: str, repo_path: str | None = None) -> dict:
    path = _config_path(scope, repo_path)
    if not path.exists():
        return {"scope": scope, "path": str(path), "servers": []}
    try:
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise CodexMcpError(f"failed to parse config: {exc}") from exc
    servers = payload.get("mcp_servers")
    if not isinstance(servers, dict):
        return {"scope": scope, "path": str(path), "servers": []}
    rows: list[dict] = []
    for name, entry in sorted(servers.items(), key=lambda item: str(item[0]).lower()):
        if not isinstance(entry, dict):
            continue
        rows.append(
            {
                "name": str(name),
                "command": str(entry.get("command") or "").strip(),
                "args": [str(item) for item in entry.get("args", [])] if isinstance(entry.get("args"), list) else [],
                "cwd": str(entry.get("cwd") or "").strip() or None,
                "env": dict(entry.get("env")) if isinstance(entry.get("env"), dict) else {},
            }
        )
    return {"scope": scope, "path": str(path), "servers": rows}


def create_codex_mcp_server(
    *,
    scope: str,
    name: str,
    command: str,
    args: list[str] | None = None,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    repo_path: str | None = None,
) -> dict:
    normalized_name = name.strip()
    normalized_command = command.strip()
    if not normalized_name:
        raise CodexMcpError("MCP server name is required")
    if not normalized_command:
        raise CodexMcpError("MCP command is required")
    try:
        existing = list_codex_mcp_servers(scope=scope, repo_path=repo_path)
    except CodexConfigError as exc:
        raise CodexMcpError(str(exc)) from exc
    if any(server["name"] == normalized_name for server in existing["servers"]):
        raise CodexMcpError(f"MCP server '{normalized_name}' already exists")

    path = Path(existing["path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    original = path.read_text(encoding="utf-8") if path.exists() else ""
    backup_path = backup_file(path)
    block = _render_mcp_block(normalized_name, normalized_command, args, cwd, env)
    path.write_text(original.rstrip() + "\n\n" + block + "\n", encoding="utf-8")
    return {
        "scope": scope,
        "path": str(path),
        "backupPath": backup_path,
        "name": normalized_name,
    }


def delete_codex_mcp_server(*, scope: str, name: str, repo_path: str | None = None) -> dict:
    normalized_name = name.strip()
    if not normalized_name:
        raise CodexMcpError("MCP server name is required")
    try:
        existing = list_codex_mcp_servers(scope=scope, repo_path=repo_path)
    except CodexConfigError as exc:
        raise CodexMcpError(str(exc)) from exc
    if not any(server["name"] == normalized_name for server in existing["servers"]):
        raise CodexMcpError(f"MCP server '{normalized_name}' does not exist")

    path = Path(existing["path"])
    original = path.read_text(encoding="utf-8")
    backup_path = backup_file(path)
    path.write_text(_remove_mcp_block(original, normalized_name), encoding="utf-8")
    return {
        "scope": scope,
        "path": str(path),
        "backupPath": backup_path,
        "name": normalized_name,
    }


def update_codex_mcp_server(
    *,
    scope: str,
    name: str,
    command: str,
    args: list[str] | None = None,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    repo_path: str | None = None,
) -> dict:
    normalized_name = name.strip()
    normalized_command = command.strip()
    if not normalized_name:
        raise CodexMcpError("MCP server name is required")
    if not normalized_command:
        raise CodexMcpError("MCP command is required")
    try:
        existing = list_codex_mcp_servers(scope=scope, repo_path=repo_path)
    except CodexConfigError as exc:
        raise CodexMcpError(str(exc)) from exc
    if not any(server["name"] == normalized_name for server in existing["servers"]):
        raise CodexMcpError(f"MCP server '{normalized_name}' does not exist")

    path = Path(existing["path"])
    original = path.read_text(encoding="utf-8")
    backup_path = backup_file(path)
    remaining = _remove_mcp_block(original, normalized_name).rstrip()
    block = _render_mcp_block(normalized_name, normalized_command, args, cwd, env)
    path.write_text((remaining + "\n\n" if remaining else "") + block + "\n", encoding="utf-8")
    return {
        "scope": scope,
        "path": str(path),
        "backupPath": backup_path,
        "name": normalized_name,
    }

from __future__ import annotations

import json
import os
import shlex
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.services.shell import command_exists


@dataclass(slots=True)
class ClaudeThreadCandidate:
    id: str
    cwd: str
    created_at: int
    updated_at: int
    title: str
    first_user_message: str
    transcript_path: str
    message_count: int


def _claude_home() -> Path:
    raw = os.environ.get("CLAUDE_HOME")
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".claude"


def _normalize_cwd_filter(cwd: str | None) -> str | None:
    if not cwd:
        return None
    expanded = Path(cwd).expanduser()
    try:
        normalized = expanded.resolve(strict=False)
    except OSError:
        normalized = expanded
    return str(normalized)


def _normalize_text(value: str | None) -> str:
    return " ".join((value or "").split()).strip().lower()


def _epoch_from_value(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = str(value).strip()
    if not text:
        return 0
    if text.isdigit():
        return int(text)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return 0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.timestamp())


def _parse_json_line(raw: str) -> dict[str, Any] | None:
    text = raw.strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _message_text(payload: dict[str, Any]) -> str:
    message = payload.get("message")
    if isinstance(message, str):
        return message.strip()
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
            return "\n".join(part.strip() for part in parts if part.strip()).strip()

    for key in ("text", "content", "prompt"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _session_files() -> list[Path]:
    root = _claude_home() / "projects"
    if not root.exists() or not root.is_dir():
        return []
    return sorted(root.rglob("*.jsonl"), key=lambda path: path.stat().st_mtime, reverse=True)


def _scan_transcript(path: Path) -> ClaudeThreadCandidate | None:
    session_id = path.stem
    cwd = ""
    first_user_message = ""
    title = ""
    created_at = 0
    updated_at = 0
    message_count = 0

    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            row = _parse_json_line(raw_line)
            if row is None:
                continue

            message_count += 1
            session_id = str(row.get("sessionId") or row.get("session_id") or row.get("uuid") or session_id).strip()
            cwd = str(row.get("cwd") or row.get("projectCwd") or row.get("project_cwd") or cwd).strip()
            timestamp = _epoch_from_value(row.get("timestamp") or row.get("created_at") or row.get("createdAt"))
            if timestamp:
                created_at = created_at or timestamp
                updated_at = max(updated_at, timestamp)

            row_type = str(row.get("type") or "").lower()
            role = str(row.get("role") or "").lower()
            if not first_user_message and (row_type == "user" or role == "user"):
                first_user_message = _message_text(row)
                title = first_user_message

    if not session_id:
        return None
    if not updated_at:
        updated_at = int(path.stat().st_mtime)
    if not created_at:
        created_at = updated_at

    return ClaudeThreadCandidate(
        id=session_id,
        cwd=cwd,
        created_at=created_at,
        updated_at=updated_at,
        title=title,
        first_user_message=first_user_message,
        transcript_path=str(path),
        message_count=message_count,
    )


def inspect_claude_environment() -> dict:
    available = command_exists("claude")
    version = ""
    version_error = ""
    if available:
        try:
            proc = subprocess.run(["claude", "--version"], text=True, capture_output=True, check=False, timeout=5)
        except subprocess.TimeoutExpired:
            version_error = "claude --version timed out"
        else:
            if proc.returncode == 0:
                version = (proc.stdout or proc.stderr).strip()
            else:
                version_error = (proc.stderr or proc.stdout).strip()

    home = _claude_home()
    projects_dir = home / "projects"
    return {
        "provider": "claude",
        "executable": "claude",
        "available": available,
        "version": version,
        "versionError": version_error,
        "authStatus": "unknown" if available else "unavailable",
        "authDetail": "Claude Code auth is verified by the CLI at launch time.",
        "claudeHome": str(home),
        "projectsPath": str(projects_dir),
        "projectsPathExists": projects_dir.exists() and projects_dir.is_dir(),
    }


def build_claude_launch_command(profile: str, prompt: str | None) -> str:
    permission_mode_by_profile = {
        "read-only": "plan",
        "safe-edit": "default",
        "full-agent": "acceptEdits",
    }
    permission_mode = permission_mode_by_profile.get(profile)
    if permission_mode is None:
        raise ValueError(f"invalid profile '{profile}'")

    command = ["claude", "--permission-mode", permission_mode]
    if prompt:
        command.append(prompt)
    return shlex.join(command)


def list_claude_threads(*, cwd: str | None = None, query: str | None = None, limit: int = 20) -> list[ClaudeThreadCandidate]:
    normalized_cwd = _normalize_cwd_filter(cwd)
    normalized_query = _normalize_text(query)
    rows: list[ClaudeThreadCandidate] = []
    seen: set[str] = set()

    for path in _session_files():
        parsed = _scan_transcript(path)
        if parsed is None or parsed.id in seen:
            continue
        if normalized_cwd and parsed.cwd and not (
            parsed.cwd == normalized_cwd or parsed.cwd.startswith(normalized_cwd.rstrip("/") + "/")
        ):
            continue
        if normalized_query:
            haystack = " ".join([parsed.id, parsed.cwd, parsed.title, parsed.first_user_message]).lower()
            if normalized_query not in haystack:
                continue
        rows.append(parsed)
        seen.add(parsed.id)
        if len(rows) >= limit:
            break

    return rows

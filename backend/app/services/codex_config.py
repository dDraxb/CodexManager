from __future__ import annotations

import copy
import json
import os
import re
import tempfile
from difflib import unified_diff
from pathlib import Path
from typing import Any
from pathlib import Path
import tomllib

from app.services.codex_environment import codex_home_path
from app.services.file_backups import backup_file, list_backups, restore_backup


class CodexConfigError(RuntimeError):
    pass


COMMON_SCALAR_KEYS = {
    "approval_policy",
    "model",
    "notify",
    "profile",
    "reasoning_effort",
    "sandbox_mode",
}
_BARE_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def _config_path(scope: str, repo_path: str | None) -> Path:
    if scope == "global":
        return codex_home_path() / "config.toml"
    if scope == "workspace":
        if not repo_path:
            raise CodexConfigError("workspace config requires a repo path")
        return Path(repo_path).expanduser() / ".codex" / "config.toml"
    raise CodexConfigError(f"invalid config scope '{scope}'")


def _parse_toml(content: str) -> dict[str, Any]:
    try:
        parsed = tomllib.loads(content or "")
    except tomllib.TOMLDecodeError as exc:
        raise CodexConfigError(f"invalid TOML: {exc}") from exc
    if not isinstance(parsed, dict):
        raise CodexConfigError("invalid TOML: root value must be an object")
    return dict(parsed)


def _scalar_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int) and not isinstance(value, bool):
        return "integer"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "unknown"


def _is_supported_scalar(value: Any) -> bool:
    return isinstance(value, (str, bool, int, float)) and not isinstance(value, bytes)


def _is_supported_array(value: Any) -> bool:
    return isinstance(value, list) and all(_is_supported_scalar(item) for item in value)


def _is_supported_toml_value(value: Any) -> bool:
    if isinstance(value, dict):
        return all(isinstance(key, str) and _is_supported_toml_value(item) for key, item in value.items())
    return _is_supported_scalar(value) or _is_supported_array(value)


def _toml_key(key: str) -> str:
    return key if _BARE_KEY_PATTERN.fullmatch(key) else json.dumps(key)


def _toml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value)
    raise CodexConfigError(f"unsupported TOML scalar value: {value!r}")


def _toml_value(value: Any) -> str:
    if _is_supported_scalar(value):
        return _toml_scalar(value)
    if _is_supported_array(value):
        return "[" + ", ".join(_toml_scalar(item) for item in value) + "]"
    raise CodexConfigError(f"unsupported TOML value: {value!r}")


def _table_header(path: list[str]) -> str:
    return "[" + ".".join(_toml_key(part) for part in path) + "]"


def _dump_toml_table(payload: dict[str, Any], prefix: list[str] | None = None) -> list[str]:
    prefix = prefix or []
    lines: list[str] = []
    scalar_items: list[tuple[str, Any]] = []
    table_items: list[tuple[str, dict[str, Any]]] = []
    for key, value in payload.items():
        if isinstance(value, dict):
            table_items.append((key, value))
        else:
            scalar_items.append((key, value))

    for key, value in scalar_items:
        lines.append(f"{_toml_key(key)} = {_toml_value(value)}")

    for key, value in table_items:
        if lines:
            lines.append("")
        elif prefix:
            lines.append("")
        table_path = [*prefix, key]
        lines.append(_table_header(table_path))
        nested = _dump_toml_table(value, table_path)
        if nested and nested[0] == "":
            nested = nested[1:]
        lines.extend(nested)

    return lines


def dump_toml_document(payload: dict[str, Any]) -> str:
    if not isinstance(payload, dict):
        raise CodexConfigError("structured config payload must be an object")
    if not _is_supported_toml_value(payload):
        raise CodexConfigError("structured config contains unsupported TOML values")
    rendered = "\n".join(_dump_toml_table(payload)).strip()
    return (rendered + "\n") if rendered else ""


def _split_structured_payload(parsed: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    scalar_fields: list[dict[str, Any]] = []
    advanced: dict[str, Any] = {}
    for key, value in parsed.items():
        if _is_supported_scalar(value) or _is_supported_array(value):
            scalar_fields.append(
                {
                    "key": key,
                    "value": value,
                    "type": _scalar_type(value),
                    "common": key in COMMON_SCALAR_KEYS,
                }
            )
        else:
            advanced[key] = value
    scalar_fields.sort(key=lambda item: (not item["common"], item["key"]))
    return scalar_fields, advanced


def _normalize_advanced_json(advanced_json: str | None) -> dict[str, Any]:
    raw = (advanced_json or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CodexConfigError(f"invalid advanced JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise CodexConfigError("advanced JSON must be an object")
    if not _is_supported_toml_value(parsed):
        raise CodexConfigError("advanced JSON contains unsupported TOML values")
    return dict(parsed)


def build_structured_codex_config(*, scalar_fields: dict[str, Any] | None = None, advanced_json: str | None = None) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in (scalar_fields or {}).items():
        normalized_key = str(key).strip()
        if not normalized_key:
            continue
        if value is None:
            continue
        if not (_is_supported_scalar(value) or _is_supported_array(value)):
            raise CodexConfigError(f"unsupported scalar field '{normalized_key}'")
        normalized[normalized_key] = value
    advanced = _normalize_advanced_json(advanced_json)
    for key, value in advanced.items():
        if key in normalized:
            raise CodexConfigError(f"advanced JSON duplicates scalar field '{key}'")
        normalized[key] = value
    return normalized


def merge_codex_config_payload(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge_codex_config_payload(dict(result[key]), value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(content)
        temp_path = Path(handle.name)
    try:
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)


def read_codex_config(*, scope: str, repo_path: str | None = None) -> dict:
    path = _config_path(scope, repo_path)
    exists = path.exists()
    content = path.read_text(encoding="utf-8") if exists else ""
    valid = True
    parse_error = None
    parsed: dict[str, Any] = {}
    scalar_fields: list[dict[str, Any]] = []
    advanced: dict[str, Any] = {}
    if content.strip():
        try:
            parsed = _parse_toml(content)
            scalar_fields, advanced = _split_structured_payload(parsed)
        except CodexConfigError as exc:
            valid = False
            parse_error = str(exc)
    return {
        "scope": scope,
        "path": str(path),
        "exists": exists,
        "content": content,
        "valid": valid,
        "parseError": parse_error,
        "parsed": parsed if valid else {},
        "scalarFields": scalar_fields if valid else [],
        "advancedJson": json.dumps(advanced, indent=2, sort_keys=True) + ("\n" if advanced else ""),
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
    _parse_toml(content or "")
    backup_path = backup_file(path)
    normalized = content.rstrip() + "\n" if content.strip() else ""
    _atomic_write_text(path, normalized)
    _parse_toml(path.read_text(encoding="utf-8") if path.exists() else "")
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


def write_structured_codex_config(
    *,
    scope: str,
    scalar_fields: dict[str, Any] | None = None,
    advanced_json: str | None = None,
    repo_path: str | None = None,
) -> dict:
    payload = build_structured_codex_config(scalar_fields=scalar_fields, advanced_json=advanced_json)
    content = dump_toml_document(payload)
    return write_codex_config(scope=scope, content=content, repo_path=repo_path)

from __future__ import annotations

import json
import tomllib
from pathlib import Path

from app.core.settings import load_settings
from app.services.codex_config import (
    CodexConfigError,
    dump_toml_document,
    merge_codex_config_payload,
    preview_codex_config,
    read_codex_config,
    write_codex_config,
)
from app.services.file_backups import backup_file, list_backups


BUILTIN_PRESETS: dict[str, dict] = {
    "safe-investigation": {
        "label": "Safe Investigation",
        "description": "Conservative defaults for low-risk inspection and scoped edits.",
        "content": 'model = "gpt-5.4"\napproval_policy = "on-request"\nsandbox_mode = "workspace-write"\nreasoning_effort = "medium"\n',
        "mode": "overlay",
    },
    "high-autonomy-refactor": {
        "label": "High Autonomy Refactor",
        "description": "Faster autonomous execution for well-understood repos.",
        "content": 'model = "gpt-5.5"\napproval_policy = "never"\nsandbox_mode = "workspace-write"\nreasoning_effort = "high"\n',
        "mode": "overlay",
    },
}
PRESET_SOURCE_ORDER = {"repo": 0, "user": 1, "builtin": 2}
PRESET_NAME_MAX_LENGTH = 64


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_toml(path: Path) -> dict:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_manager_preset_library() -> dict:
    settings = load_settings()
    candidates = [
        (settings.app_home / "config-presets.json", _load_json),
        (settings.app_home / "config-presets.toml", _load_toml),
        (settings.app_home / "presets" / "config.json", _load_json),
        (settings.app_home / "presets" / "config.toml", _load_toml),
    ]
    for path, loader in candidates:
        if not path.exists():
            continue
        payload = loader(path)
        if not isinstance(payload, dict):
            continue
        presets = payload.get("presets") if isinstance(payload.get("presets"), dict) else payload
        if isinstance(presets, dict):
            return presets
    return {}


def _manager_preset_library_path() -> Path:
    return load_settings().app_home / "config-presets.json"


def _load_repo_preset_library(repo_path: str | None) -> dict:
    if not repo_path:
        return {}
    root = Path(repo_path).expanduser()
    candidates = [
        (root / ".codex" / "config-presets.json", _load_json),
        (root / ".codex" / "config-presets.toml", _load_toml),
        (root / ".codex" / "presets" / "config.json", _load_json),
        (root / ".codex" / "presets" / "config.toml", _load_toml),
    ]
    for path, loader in candidates:
        if not path.exists():
            continue
        payload = loader(path)
        if not isinstance(payload, dict):
            continue
        presets = payload.get("presets") if isinstance(payload.get("presets"), dict) else payload
        if isinstance(presets, dict):
            return presets
    return {}


def _repo_preset_library_path(repo_path: str) -> Path:
    root = Path(repo_path).expanduser()
    return root / ".codex" / "config-presets.json"


def _normalize_preset_id(preset_id: str) -> str:
    normalized = str(preset_id).strip()
    if not normalized:
        raise CodexConfigError("preset id is required")
    if len(normalized) > PRESET_NAME_MAX_LENGTH:
        raise CodexConfigError("preset id is too long")
    return normalized


def _normalize_preset_mode(mode: str | None) -> str:
    normalized = str(mode or "overlay").strip().lower()
    if normalized not in {"overlay", "replace"}:
        raise CodexConfigError(f"invalid preset mode '{normalized}'")
    return normalized


def _library_payload(path: Path) -> dict:
    if not path.exists():
        return {"presets": {}}
    payload = _load_json(path)
    if not isinstance(payload, dict):
        return {"presets": {}}
    presets = payload.get("presets")
    if not isinstance(presets, dict):
        presets = {}
    return {"presets": dict(presets)}


def _save_library_payload(path: Path, payload: dict) -> str | None:
    path.parent.mkdir(parents=True, exist_ok=True)
    backup_path = backup_file(path)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return backup_path


def _preset_library(scope: str, repo_path: str | None) -> tuple[str, Path, dict]:
    if scope == "user":
        path = _manager_preset_library_path()
        return scope, path, _library_payload(path)
    if scope == "repo":
        if not repo_path:
            raise CodexConfigError("repo preset scope requires a repo path")
        path = _repo_preset_library_path(repo_path)
        return scope, path, _library_payload(path)
    raise CodexConfigError(f"invalid preset scope '{scope}'")


def _preset_rows(presets: dict, *, source: str, repo_path: str | None = None) -> list[dict]:
    rows: list[dict] = []
    for preset_id, payload in presets.items():
        if not isinstance(payload, dict):
            continue
        content = str(payload.get("content") or "").strip()
        if not content:
            continue
        mode = str(payload.get("mode") or "overlay").strip().lower()
        if mode not in {"overlay", "replace"}:
            mode = "overlay"
        rows.append(
            {
                "id": str(preset_id),
                "label": str(payload.get("label") or preset_id).strip(),
                "description": str(payload.get("description") or "").strip(),
                "content": content + "\n",
                "mode": mode,
                "source": source,
                "repoPath": repo_path,
            }
        )
    return rows


def list_manager_codex_config_presets(repo_path: str | None = None) -> list[dict]:
    merged: dict[str, dict] = {}
    for row in _preset_rows(BUILTIN_PRESETS, source="builtin"):
        merged[row["id"]] = row
    for row in _preset_rows(_load_manager_preset_library(), source="user"):
        merged[row["id"]] = row
    for row in _preset_rows(_load_repo_preset_library(repo_path), source="repo", repo_path=repo_path):
        merged[row["id"]] = row
    return sorted(merged.values(), key=lambda row: (PRESET_SOURCE_ORDER.get(row["source"], 99), row["id"]))


def list_saved_codex_config_presets(scope: str, repo_path: str | None = None) -> dict:
    normalized_scope, path, payload = _preset_library(scope, repo_path)
    rows = _preset_rows(payload.get("presets", {}), source=normalized_scope, repo_path=repo_path if normalized_scope == "repo" else None)
    rows.sort(key=lambda row: row["id"])
    return {
        "scope": normalized_scope,
        "path": str(path),
        "exists": path.exists(),
        "presets": rows,
        "backups": list_backups(path),
    }


def save_codex_config_preset(
    *,
    scope: str,
    preset_id: str,
    label: str,
    description: str,
    content: str,
    mode: str = "overlay",
    repo_path: str | None = None,
) -> dict:
    normalized_id = _normalize_preset_id(preset_id)
    normalized_mode = _normalize_preset_mode(mode)
    try:
        tomllib.loads(content or "")
    except tomllib.TOMLDecodeError as exc:
        raise CodexConfigError(f"invalid preset TOML: {exc}") from exc

    normalized_scope, path, payload = _preset_library(scope, repo_path)
    presets = dict(payload.get("presets", {}))
    presets[normalized_id] = {
        "label": str(label or normalized_id).strip() or normalized_id,
        "description": str(description or "").strip(),
        "content": content.rstrip() + "\n",
        "mode": normalized_mode,
    }
    payload["presets"] = presets
    backup_path = _save_library_payload(path, payload)
    return {
        "scope": normalized_scope,
        "path": str(path),
        "backupPath": backup_path,
        "preset": _preset_rows({normalized_id: presets[normalized_id]}, source=normalized_scope, repo_path=repo_path if normalized_scope == "repo" else None)[0],
    }


def delete_codex_config_preset(*, scope: str, preset_id: str, repo_path: str | None = None) -> dict:
    normalized_id = _normalize_preset_id(preset_id)
    normalized_scope, path, payload = _preset_library(scope, repo_path)
    presets = dict(payload.get("presets", {}))
    if normalized_id not in presets:
        raise CodexConfigError(f"config preset '{normalized_id}' does not exist")
    deleted = presets.pop(normalized_id)
    payload["presets"] = presets
    backup_path = _save_library_payload(path, payload)
    return {
        "scope": normalized_scope,
        "path": str(path),
        "backupPath": backup_path,
        "preset": _preset_rows({normalized_id: deleted}, source=normalized_scope, repo_path=repo_path if normalized_scope == "repo" else None)[0],
    }


def get_manager_codex_config_preset(preset_id: str, repo_path: str | None = None) -> dict:
    rows = list_manager_codex_config_presets(repo_path)
    preset = next((row for row in rows if row["id"] == preset_id), None)
    if preset is None:
        raise CodexConfigError(f"config preset '{preset_id}' does not exist")
    return preset


def resolve_codex_config_preset_content(
    *,
    scope: str,
    preset_id: str,
    repo_path: str | None = None,
    mode: str | None = None,
) -> tuple[dict, str]:
    preset = get_manager_codex_config_preset(preset_id, repo_path)
    effective_mode = str(mode or preset.get("mode") or "overlay").strip().lower()
    if effective_mode not in {"overlay", "replace"}:
        raise CodexConfigError(f"invalid preset apply mode '{effective_mode}'")
    preset_payload = tomllib.loads(preset["content"])
    if effective_mode == "replace":
        return preset, dump_toml_document(dict(preset_payload))

    current = read_codex_config(scope=scope, repo_path=repo_path)
    current_payload = tomllib.loads(current["content"]) if current["content"].strip() else {}
    merged = merge_codex_config_payload(dict(current_payload), dict(preset_payload))
    return preset, dump_toml_document(merged)


def preview_apply_codex_config_preset(
    *,
    scope: str,
    preset_id: str,
    repo_path: str | None = None,
    mode: str | None = None,
) -> dict:
    preset, content = resolve_codex_config_preset_content(scope=scope, preset_id=preset_id, repo_path=repo_path, mode=mode)
    payload = preview_codex_config(scope=scope, content=content, repo_path=repo_path)
    payload["preset"] = {
        "id": preset["id"],
        "label": preset["label"],
        "source": preset["source"],
        "mode": str(mode or preset["mode"]),
    }
    return payload


def apply_codex_config_preset(
    *,
    scope: str,
    preset_id: str,
    repo_path: str | None = None,
    mode: str | None = None,
) -> dict:
    preset, content = resolve_codex_config_preset_content(scope=scope, preset_id=preset_id, repo_path=repo_path, mode=mode)
    payload = write_codex_config(scope=scope, content=content, repo_path=repo_path)
    payload["preset"] = {
        "id": preset["id"],
        "label": preset["label"],
        "source": preset["source"],
        "mode": str(mode or preset["mode"]),
    }
    return payload

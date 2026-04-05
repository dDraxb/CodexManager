from __future__ import annotations

import json
import tomllib
from pathlib import Path

from app.core.settings import load_settings
from app.services.codex_config import CodexConfigError


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


def list_manager_codex_config_presets() -> list[dict]:
    presets = _load_manager_preset_library()
    rows: list[dict] = []
    for preset_id, payload in presets.items():
        if not isinstance(payload, dict):
            continue
        content = str(payload.get("content") or "").strip()
        if not content:
            continue
        rows.append(
            {
                "id": str(preset_id),
                "label": str(payload.get("label") or preset_id).strip(),
                "description": str(payload.get("description") or "").strip(),
                "content": content + "\n",
            }
        )
    rows.sort(key=lambda row: row["id"])
    return rows


def get_manager_codex_config_preset(preset_id: str) -> dict:
    rows = list_manager_codex_config_presets()
    preset = next((row for row in rows if row["id"] == preset_id), None)
    if preset is None:
        raise CodexConfigError(f"config preset '{preset_id}' does not exist")
    return preset

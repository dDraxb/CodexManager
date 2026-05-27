from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

from app.core.settings import load_settings


class HistoryViewError(RuntimeError):
    pass


VIEW_ID_MAX_LENGTH = 64
VALID_ARCHIVED_VALUES = {"all", "true", "false"}
VALID_FILTER_KEYS = {
    "query",
    "repoPath",
    "status",
    "profile",
    "validationState",
    "archived",
}


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _views_path() -> Path:
    return load_settings().app_home / "history-views.json"


def _load_payload(path: Path) -> dict:
    if not path.exists():
        return {"views": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"views": {}}
    views = payload.get("views") if isinstance(payload, dict) else {}
    return {"views": views if isinstance(views, dict) else {}}


def _save_payload(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _normalize_view_id(view_id: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(view_id or "").strip().lower()).strip("-")
    if not normalized:
        raise HistoryViewError("history view id is required")
    if len(normalized) > VIEW_ID_MAX_LENGTH:
        raise HistoryViewError("history view id is too long")
    return normalized


def _normalize_filters(filters: dict | None) -> dict:
    raw = filters if isinstance(filters, dict) else {}
    archived = str(raw.get("archived") or "all").strip().lower()
    if archived not in VALID_ARCHIVED_VALUES:
        archived = "all"
    normalized = {
        "query": str(raw.get("query") or "").strip(),
        "repoPath": str(raw.get("repoPath") or "").strip(),
        "status": str(raw.get("status") or "").strip(),
        "profile": str(raw.get("profile") or "").strip(),
        "validationState": str(raw.get("validationState") or "").strip(),
        "archived": archived,
    }
    return {key: normalized[key] for key in VALID_FILTER_KEYS}


def _view_row(view_id: str, payload: dict) -> dict:
    filters = _normalize_filters(payload.get("filters") if isinstance(payload, dict) else {})
    return {
        "id": view_id,
        "label": str(payload.get("label") or view_id).strip() if isinstance(payload, dict) else view_id,
        "description": str(payload.get("description") or "").strip() if isinstance(payload, dict) else "",
        "filters": filters,
        "createdAt": str(payload.get("createdAt") or "") if isinstance(payload, dict) else "",
        "updatedAt": str(payload.get("updatedAt") or "") if isinstance(payload, dict) else "",
    }


def list_history_views() -> dict:
    path = _views_path()
    payload = _load_payload(path)
    rows = [_view_row(view_id, view) for view_id, view in payload["views"].items() if isinstance(view, dict)]
    rows.sort(key=lambda row: (row["label"].lower(), row["id"]))
    return {
        "path": str(path),
        "exists": path.exists(),
        "views": rows,
    }


def save_history_view(*, view_id: str, label: str, description: str = "", filters: dict | None = None) -> dict:
    normalized_id = _normalize_view_id(view_id)
    normalized_filters = _normalize_filters(filters)
    path = _views_path()
    payload = _load_payload(path)
    existing = payload["views"].get(normalized_id) if isinstance(payload["views"].get(normalized_id), dict) else {}
    now = _now_iso()
    row = {
        "label": str(label or normalized_id).strip() or normalized_id,
        "description": str(description or "").strip(),
        "filters": normalized_filters,
        "createdAt": existing.get("createdAt") or now,
        "updatedAt": now,
    }
    payload["views"][normalized_id] = row
    _save_payload(path, payload)
    return {
        "path": str(path),
        "view": _view_row(normalized_id, row),
    }


def delete_history_view(view_id: str) -> dict:
    normalized_id = _normalize_view_id(view_id)
    path = _views_path()
    payload = _load_payload(path)
    existing = payload["views"].pop(normalized_id, None)
    if existing is None:
        raise HistoryViewError(f"history view '{normalized_id}' does not exist")
    _save_payload(path, payload)
    return {
        "path": str(path),
        "view": _view_row(normalized_id, existing if isinstance(existing, dict) else {}),
    }

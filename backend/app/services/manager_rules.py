from __future__ import annotations

import json
from pathlib import Path

from app.core.settings import load_settings
from app.services.file_backups import backup_file, list_backups, restore_backup

SESSION_DEFAULT_RULE_CATEGORY = "session_defaults"


class ManagerRulesError(RuntimeError):
    pass


def _manager_rules_path() -> Path:
    return load_settings().app_home / "manager-rules.json"


def _normalized_scope(scope: object) -> dict[str, str]:
    if isinstance(scope, str):
        level = scope.strip() or "global"
        return {"level": level, "repo_path": "", "preset_id": ""}
    if isinstance(scope, dict):
        return {
            "level": str(scope.get("level") or "global").strip() or "global",
            "repo_path": str(scope.get("repo_path") or "").strip(),
            "preset_id": str(scope.get("preset_id") or "").strip(),
        }
    return {"level": "global", "repo_path": "", "preset_id": ""}


def _scope_summary(scope: object) -> str:
    normalized = _normalized_scope(scope)
    parts: list[str] = []
    if normalized["level"]:
        parts.append(normalized["level"])
    if normalized["repo_path"]:
        parts.append(normalized["repo_path"])
    if normalized["preset_id"]:
        parts.append(f"preset:{normalized['preset_id']}")
    return " · ".join(parts) if parts else "global"


def _path_matches(prefix: str, repo_path: str | None) -> bool:
    normalized_repo_path = str(repo_path or "").strip()
    normalized_prefix = prefix.strip().rstrip("/")
    if not normalized_repo_path or not normalized_prefix:
        return False
    return normalized_repo_path == normalized_prefix or normalized_repo_path.startswith(f"{normalized_prefix}/")


def _matches_scope(scope: dict[str, str], *, repo_path: str | None, preset_id: str | None) -> bool:
    level = scope["level"]
    if level == "global":
        return True
    if level == "workspace":
        return _path_matches(scope["repo_path"], repo_path)
    if level == "preset":
        return bool(scope["preset_id"]) and scope["preset_id"] == str(preset_id or "").strip()
    return False


def _scope_specificity(scope: dict[str, str]) -> tuple[int, int]:
    level = scope["level"]
    if level == "workspace":
        return (2, len(scope["repo_path"]))
    if level == "preset":
        return (1, len(scope["preset_id"]))
    return (0, 0)


def _normalize_rule(index: int, payload: object) -> dict:
    if not isinstance(payload, dict):
        raise ManagerRulesError(f"rule {index + 1} must be an object")

    rule_id = str(payload.get("id") or "").strip()
    if not rule_id:
        raise ManagerRulesError(f"rule {index + 1} is missing a non-empty 'id'")

    label = str(payload.get("label") or rule_id).strip() or rule_id
    category = str(payload.get("category") or "general").strip() or "general"
    enabled = payload.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ManagerRulesError(f"rule '{rule_id}' has invalid 'enabled'; expected boolean")

    content = payload.get("content")
    if not isinstance(content, dict):
        raise ManagerRulesError(f"rule '{rule_id}' has invalid 'content'; expected object")

    notes = str(payload.get("notes") or "").strip()
    scope = _normalized_scope(payload.get("scope"))
    return {
        "id": rule_id,
        "label": label,
        "category": category,
        "enabled": enabled,
        "scope": scope,
        "scopeSummary": _scope_summary(scope),
        "notes": notes,
        "contentKeys": sorted(content.keys()),
        "content": content,
    }


def _parse_rules_document(content: str) -> tuple[dict, list[dict]]:
    if not content.strip():
        return {"version": 1, "rules": []}, []
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ManagerRulesError(f"invalid JSON: {exc.msg} at line {exc.lineno} column {exc.colno}") from exc
    if not isinstance(payload, dict):
        raise ManagerRulesError("manager rules document must be a JSON object")
    version = payload.get("version", 1)
    if not isinstance(version, int):
        raise ManagerRulesError("manager rules 'version' must be an integer")
    rules = payload.get("rules", [])
    if not isinstance(rules, list):
        raise ManagerRulesError("manager rules 'rules' must be an array")
    summaries = [_normalize_rule(index, rule) for index, rule in enumerate(rules)]
    normalized = {
        "version": version,
        "rules": rules,
    }
    return normalized, summaries


def read_manager_rules() -> dict:
    path = _manager_rules_path()
    exists = path.exists()
    content = path.read_text(encoding="utf-8") if exists else ""
    parse_error = None
    rules: list[dict] = []
    valid = True
    if exists:
        try:
            _, rules = _parse_rules_document(content)
        except ManagerRulesError as exc:
            valid = False
            parse_error = str(exc)
    return {
        "path": str(path),
        "exists": exists,
        "content": content,
        "backups": list_backups(path),
        "valid": valid,
        "parseError": parse_error,
        "rules": rules,
        "ruleCount": len(rules),
    }


def list_matching_manager_rules(
    *,
    repo_path: str | None = None,
    preset_id: str | None = None,
    category: str | None = None,
) -> list[dict]:
    payload = read_manager_rules()
    if payload["valid"] is False:
        raise ManagerRulesError(payload["parseError"] or "manager rules are invalid")

    rows: list[tuple[tuple[int, int], dict]] = []
    for rule in payload["rules"]:
        if not rule.get("enabled", True):
            continue
        if category and rule.get("category") != category:
            continue
        scope = rule.get("scope") if isinstance(rule.get("scope"), dict) else _normalized_scope("global")
        if not _matches_scope(scope, repo_path=repo_path, preset_id=preset_id):
            continue
        rows.append((_scope_specificity(scope), rule))

    rows.sort(key=lambda item: item[0])
    return [
        {
            "id": rule["id"],
            "label": rule["label"],
            "category": rule["category"],
            "scopeSummary": rule["scopeSummary"],
            "notes": rule["notes"],
            "contentKeys": rule["contentKeys"],
        }
        for _, rule in rows
    ]


def effective_session_defaults(*, repo_path: str | None = None, preset_id: str | None = None) -> dict:
    payload = read_manager_rules()
    if payload["valid"] is False:
        raise ManagerRulesError(payload["parseError"] or "manager rules are invalid")

    merged: dict[str, object] = {}
    applied_rules: list[dict] = []
    for scope_rank, rule in sorted(
        (
            (_scope_specificity(rule.get("scope") if isinstance(rule.get("scope"), dict) else _normalized_scope("global")), rule)
            for rule in payload["rules"]
            if rule.get("enabled", True) and rule.get("category") == SESSION_DEFAULT_RULE_CATEGORY
        ),
        key=lambda item: item[0],
    ):
        scope = rule.get("scope") if isinstance(rule.get("scope"), dict) else _normalized_scope("global")
        if not _matches_scope(scope, repo_path=repo_path, preset_id=preset_id):
            continue
        content = rule.get("content") if isinstance(rule.get("content"), dict) else {}
        if isinstance(content.get("profile"), str) and content.get("profile"):
            merged["profile"] = str(content["profile"]).strip()
        if isinstance(content.get("approval_policy"), str) and content.get("approval_policy"):
            merged["approvalPolicy"] = str(content["approval_policy"]).strip()
        if isinstance(content.get("create_worktree_for_writes"), bool):
            merged["createWorktreeForWrites"] = content["create_worktree_for_writes"]
        if isinstance(content.get("auto_init_git"), bool):
            merged["autoInitGit"] = content["auto_init_git"]
        if isinstance(content.get("require_changelog"), bool):
            merged["requireChangelog"] = content["require_changelog"]
        if isinstance(content.get("launch"), bool):
            merged["launch"] = content["launch"]
        applied_rules.append(
            {
                "id": rule["id"],
                "label": rule["label"],
                "scopeSummary": rule["scopeSummary"],
                "notes": rule["notes"],
                "specificity": list(scope_rank),
            }
        )

    return {
        "defaults": merged,
        "appliedRules": applied_rules,
    }


def write_manager_rules(*, content: str) -> dict:
    path = _manager_rules_path()
    normalized, summaries = _parse_rules_document(content)
    path.parent.mkdir(parents=True, exist_ok=True)
    backup_path = backup_file(path)
    serialized = json.dumps(normalized, indent=2) + "\n"
    path.write_text(serialized, encoding="utf-8")
    return {
        "path": str(path),
        "backupPath": backup_path,
        "ruleCount": len(summaries),
    }


def restore_manager_rules(*, backup_path: str) -> dict:
    path = _manager_rules_path()
    try:
        restored = restore_backup(path, backup_path)
    except FileNotFoundError as exc:
        raise ManagerRulesError(str(exc)) from exc
    return restored

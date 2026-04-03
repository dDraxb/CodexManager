from __future__ import annotations

import json
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path

from app.core.settings import load_settings


@dataclass(frozen=True, slots=True)
class RepoPolicyRule:
    policy_id: str
    label: str
    path_prefixes: list[str]
    protected_branches: list[str]
    require_worktree_for_write: bool
    require_changelog: bool
    default_profile: str | None
    default_approval_policy: str | None


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


def _load_policy_payloads() -> dict:
    settings = load_settings()
    candidates = [
        (settings.app_home / "repo-policies.json", _load_json),
        (settings.app_home / "repo-policies.toml", _load_toml),
        (settings.app_home / "policies" / "repo.json", _load_json),
        (settings.app_home / "policies" / "repo.toml", _load_toml),
    ]
    for path, loader in candidates:
        if not path.exists():
            continue
        payload = loader(path)
        if not isinstance(payload, dict):
            continue
        policies = payload.get("policies") if isinstance(payload.get("policies"), dict) else payload
        return policies if isinstance(policies, dict) else {}
    return {}


def _normalize_rule(policy_id: str, payload: dict) -> RepoPolicyRule | None:
    if not isinstance(payload, dict):
        return None
    match = payload.get("match") if isinstance(payload.get("match"), dict) else {}
    defaults = payload.get("defaults") if isinstance(payload.get("defaults"), dict) else {}
    rules = payload.get("rules") if isinstance(payload.get("rules"), dict) else {}
    path_prefixes = [str(item).strip() for item in match.get("path_prefixes", []) if str(item).strip()]
    if not path_prefixes:
        return None
    protected_branches = [str(item).strip().lower() for item in rules.get("protected_branches", ["main", "master"]) if str(item).strip()]
    return RepoPolicyRule(
        policy_id=policy_id,
        label=str(payload.get("label") or policy_id).strip(),
        path_prefixes=path_prefixes,
        protected_branches=protected_branches or ["main", "master"],
        require_worktree_for_write=bool(rules.get("require_worktree_for_write", False)),
        require_changelog=bool(defaults.get("require_changelog", False)),
        default_profile=str(defaults.get("profile")).strip() if defaults.get("profile") else None,
        default_approval_policy=str(defaults.get("approval_policy")).strip() if defaults.get("approval_policy") else None,
    )


def list_repo_policies() -> list[dict]:
    rows: list[dict] = []
    for policy_id, payload in _load_policy_payloads().items():
        rule = _normalize_rule(str(policy_id), payload)
        if rule is None:
            continue
        rows.append(asdict(rule))
    rows.sort(key=lambda row: row["policy_id"])
    return rows


def match_repo_policy(repo_path: str) -> RepoPolicyRule | None:
    repo = str(Path(repo_path).expanduser().resolve())
    best: tuple[int, RepoPolicyRule] | None = None
    for policy_id, payload in _load_policy_payloads().items():
        rule = _normalize_rule(str(policy_id), payload)
        if rule is None:
            continue
        for prefix in rule.path_prefixes:
            normalized_prefix = str(Path(prefix).expanduser())
            if repo == normalized_prefix or repo.startswith(f"{normalized_prefix.rstrip('/')}/"):
                score = len(normalized_prefix)
                if best is None or score > best[0]:
                    best = (score, rule)
    return best[1] if best else None


def serialize_repo_policy(rule: RepoPolicyRule | None) -> tuple[str | None, str | None, str | None]:
    if rule is None:
        return None, None, None
    return rule.policy_id, rule.label, json.dumps(asdict(rule))


def parse_repo_policy(raw_policy_json: str | None) -> dict:
    if not raw_policy_json:
        return {}
    try:
        payload = json.loads(raw_policy_json)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}

from __future__ import annotations

import json
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path

from app.core.settings import load_settings


@dataclass(frozen=True, slots=True)
class ValidationCheck:
    kind: str
    label: str
    command: str
    required: bool = True


@dataclass(frozen=True, slots=True)
class ValidationRecipe:
    recipe_id: str
    label: str
    checks: list[ValidationCheck]


ALLOWED_KINDS = {"tests", "lint", "build"}


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


def _load_recipe_payload(raw_recipe_json: str | None) -> dict:
    if not raw_recipe_json:
        return {}
    try:
        payload = json.loads(raw_recipe_json)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _normalize_custom_recipe(payload: dict, recipe_id: str) -> ValidationRecipe | None:
    checks_payload = payload.get("checks")
    if not isinstance(checks_payload, list) or not checks_payload:
        return None

    checks: list[ValidationCheck] = []
    for item in checks_payload:
        if not isinstance(item, dict):
            return None
        kind = str(item.get("kind") or "").strip().lower()
        command = str(item.get("command") or "").strip()
        label = str(item.get("label") or kind.title()).strip()
        required = bool(item.get("required", True))
        if kind not in ALLOWED_KINDS or not command:
            return None
        checks.append(ValidationCheck(kind, label, command, required=required))

    label = str(payload.get("label") or "Custom validation").strip()
    return ValidationRecipe(recipe_id, label, checks)


def _load_manager_preset_library() -> dict:
    settings = load_settings()
    candidates = [
        (settings.app_home / "validation-presets.json", _load_json),
        (settings.app_home / "validation-presets.toml", _load_toml),
        (settings.app_home / "presets" / "validation.json", _load_json),
        (settings.app_home / "presets" / "validation.toml", _load_toml),
    ]
    for path, loader in candidates:
        if not path.exists():
            continue
        payload = loader(path)
        if not isinstance(payload, dict):
            continue
        presets = payload.get("presets") if isinstance(payload.get("presets"), dict) else payload
        return presets if isinstance(presets, dict) else {}
    return {}


def _recipe_from_preset_id(preset_id: str) -> ValidationRecipe | None:
    presets = _load_manager_preset_library()
    payload = presets.get(preset_id)
    if not isinstance(payload, dict):
        return None
    return _normalize_custom_recipe(payload, f"preset:{preset_id}")


def list_manager_validation_presets() -> list[dict]:
    presets = _load_manager_preset_library()
    rows: list[dict] = []
    for preset_id, payload in presets.items():
        if not isinstance(payload, dict):
            continue
        recipe = _normalize_custom_recipe(payload, f"preset:{preset_id}")
        if recipe is None:
            continue
        rows.append(
            {
                "id": preset_id,
                "recipe_id": recipe.recipe_id,
                "label": recipe.label,
                "checks": [asdict(check) for check in recipe.checks],
            }
        )
    rows.sort(key=lambda row: row["id"])
    return rows


def _custom_recipe(root: Path) -> ValidationRecipe | None:
    candidates = [
        (root / ".codexmgr" / "validation.json", _load_json, "custom-json"),
        (root / ".codexmgr.validation.json", _load_json, "custom-json"),
        (root / ".codexmgr" / "validation.toml", _load_toml, "custom-toml"),
        (root / ".codexmgr.validation.toml", _load_toml, "custom-toml"),
    ]
    for path, loader, recipe_id in candidates:
        if not path.exists():
            continue
        payload = loader(path)
        if not isinstance(payload, dict):
            continue
        preset_id = str(payload.get("preset") or "").strip()
        if preset_id:
            recipe = _recipe_from_preset_id(preset_id)
            if recipe is not None:
                return recipe
        recipe = _normalize_custom_recipe(payload, recipe_id)
        if recipe is not None:
            return recipe
    return None


def _node_recipe(root: Path) -> ValidationRecipe | None:
    package_json = root / "package.json"
    if not package_json.exists():
        return None
    payload = _load_json(package_json)
    scripts = payload.get("scripts") or {}
    checks: list[ValidationCheck] = []
    if "test" in scripts:
        checks.append(ValidationCheck("tests", "Tests", "npm test"))
    if "lint" in scripts:
        checks.append(ValidationCheck("lint", "Lint", "npm run lint"))
    if "build" in scripts:
        checks.append(ValidationCheck("build", "Build", "npm run build"))
    if not checks:
        checks.append(ValidationCheck("tests", "Tests", "npm test"))
    return ValidationRecipe("node", "Node.js", checks)


def _python_recipe(root: Path) -> ValidationRecipe | None:
    pyproject = root / "pyproject.toml"
    setup_py = root / "setup.py"
    requirements = root / "requirements.txt"
    if not pyproject.exists() and not setup_py.exists() and not requirements.exists():
        return None
    checks: list[ValidationCheck] = [ValidationCheck("tests", "Tests", "pytest")]
    pyproject_data = _load_toml(pyproject) if pyproject.exists() else {}
    if pyproject.exists() or (root / ".ruff.toml").exists() or (root / "ruff.toml").exists():
        checks.append(ValidationCheck("lint", "Lint", "ruff check ."))
    if pyproject_data.get("build-system"):
        checks.append(ValidationCheck("build", "Build", "python -m build"))
    return ValidationRecipe("python", "Python", checks)


def _rust_recipe(root: Path) -> ValidationRecipe | None:
    if not (root / "Cargo.toml").exists():
        return None
    return ValidationRecipe(
        "rust",
        "Rust",
        [
            ValidationCheck("tests", "Tests", "cargo test"),
            ValidationCheck("lint", "Lint", "cargo clippy"),
            ValidationCheck("build", "Build", "cargo build"),
        ],
    )


def _go_recipe(root: Path) -> ValidationRecipe | None:
    if not (root / "go.mod").exists():
        return None
    return ValidationRecipe(
        "go",
        "Go",
        [
            ValidationCheck("tests", "Tests", "go test ./..."),
            ValidationCheck("build", "Build", "go build ./..."),
        ],
    )


def _php_recipe(root: Path) -> ValidationRecipe | None:
    composer_json = root / "composer.json"
    if not composer_json.exists():
        return None
    raw = composer_json.read_text(encoding="utf-8", errors="ignore")
    payload = _load_json(composer_json)
    scripts = payload.get("scripts") or {}
    checks: list[ValidationCheck] = []
    if "phpunit" in raw or "test" in scripts:
        checks.append(ValidationCheck("tests", "Tests", "phpunit"))
    if "phpstan" in raw or "lint" in scripts:
        checks.append(ValidationCheck("lint", "Lint", "phpstan"))
    if not checks:
        checks.append(ValidationCheck("tests", "Tests", "phpunit"))
    return ValidationRecipe("php", "PHP", checks)


def detect_validation_recipe(repo_path: str) -> ValidationRecipe | None:
    root = Path(repo_path)
    if not root.exists() or not root.is_dir():
        return None
    custom = _custom_recipe(root)
    if custom is not None:
        return custom
    for detector in (_node_recipe, _python_recipe, _rust_recipe, _go_recipe, _php_recipe):
        recipe = detector(root)
        if recipe is not None:
            return recipe
    return None


def missing_validation_checks(
    raw_recipe_json: str | None,
    *,
    test_status: str | None,
    lint_status: str | None,
    build_status: str | None,
) -> list[str]:
    payload = _load_recipe_payload(raw_recipe_json)
    checks = payload.get("checks")
    if not isinstance(checks, list):
        return []

    observed = {
        "tests": test_status if test_status and test_status != "unknown" else None,
        "lint": lint_status if lint_status and lint_status != "unknown" else None,
        "build": build_status if build_status and build_status != "unknown" else None,
    }
    missing: list[str] = []
    for item in checks:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip().lower()
        required = bool(item.get("required", True))
        if required and kind in ALLOWED_KINDS and observed.get(kind) is None and kind not in missing:
            missing.append(kind)
    return missing


def optional_pending_validation_checks(
    raw_recipe_json: str | None,
    *,
    test_status: str | None,
    lint_status: str | None,
    build_status: str | None,
) -> list[str]:
    payload = _load_recipe_payload(raw_recipe_json)
    checks = payload.get("checks")
    if not isinstance(checks, list):
        return []

    observed = {
        "tests": test_status if test_status and test_status != "unknown" else None,
        "lint": lint_status if lint_status and lint_status != "unknown" else None,
        "build": build_status if build_status and build_status != "unknown" else None,
    }
    pending: list[str] = []
    for item in checks:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip().lower()
        required = bool(item.get("required", True))
        if not required and kind in ALLOWED_KINDS and observed.get(kind) is None and kind not in pending:
            pending.append(kind)
    return pending


def validation_policy_state(
    raw_recipe_json: str | None,
    *,
    test_status: str | None,
    lint_status: str | None,
    build_status: str | None,
) -> tuple[str, str | None, list[str], list[str]]:
    required_missing = missing_validation_checks(
        raw_recipe_json,
        test_status=test_status,
        lint_status=lint_status,
        build_status=build_status,
    )
    optional_pending = optional_pending_validation_checks(
        raw_recipe_json,
        test_status=test_status,
        lint_status=lint_status,
        build_status=build_status,
    )
    payload = _load_recipe_payload(raw_recipe_json)
    checks = payload.get("checks")
    if not isinstance(checks, list) or not checks:
        return "unknown", None, required_missing, optional_pending
    if required_missing:
        return "required_missing", f"required checks still missing: {', '.join(required_missing)}", required_missing, optional_pending
    if optional_pending:
        return "optional_pending", f"optional checks still pending: {', '.join(optional_pending)}", required_missing, optional_pending
    return "ready", "all required validation checks have been observed", required_missing, optional_pending


def serialize_validation_recipe(recipe: ValidationRecipe | None) -> tuple[str | None, str]:
    if recipe is None:
        return None, "[]"
    return recipe.recipe_id, json.dumps(
        {
            "label": recipe.label,
            "checks": [asdict(check) for check in recipe.checks],
        }
    )


def materialize_validation_recipe_payload(raw_recipe_json: str | None) -> dict:
    payload = _load_recipe_payload(raw_recipe_json)
    recipe = _normalize_custom_recipe(payload, "materialized")
    if recipe is None:
        raise ValueError("validation recipe is not available to materialize")
    return {
        "label": recipe.label,
        "checks": [asdict(check) for check in recipe.checks],
    }

from __future__ import annotations

import json
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ValidationCheck:
    kind: str
    label: str
    command: str


@dataclass(frozen=True, slots=True)
class ValidationRecipe:
    recipe_id: str
    label: str
    checks: list[ValidationCheck]


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
    for detector in (_node_recipe, _python_recipe, _rust_recipe, _go_recipe, _php_recipe):
        recipe = detector(root)
        if recipe is not None:
            return recipe
    return None


def serialize_validation_recipe(recipe: ValidationRecipe | None) -> tuple[str | None, str]:
    if recipe is None:
        return None, "[]"
    return recipe.recipe_id, json.dumps(
        {
            "label": recipe.label,
            "checks": [asdict(check) for check in recipe.checks],
        }
    )

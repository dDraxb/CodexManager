from __future__ import annotations

import json


def test_detect_validation_recipe_for_node_project(tmp_path):
    from app.services.validation_recipe import detect_validation_recipe, serialize_validation_recipe

    project = tmp_path / "node-app"
    project.mkdir()
    (project / "package.json").write_text(
        json.dumps({"scripts": {"test": "vitest", "lint": "eslint .", "build": "vite build"}}),
        encoding="utf-8",
    )

    recipe = detect_validation_recipe(str(project))

    assert recipe is not None
    assert recipe.recipe_id == "node"
    assert [check.kind for check in recipe.checks] == ["tests", "lint", "build"]
    recipe_id, payload = serialize_validation_recipe(recipe)
    assert recipe_id == "node"
    assert json.loads(payload)["label"] == "Node.js"


def test_detect_validation_recipe_for_python_project(tmp_path):
    from app.services.validation_recipe import detect_validation_recipe

    project = tmp_path / "python-app"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        """
[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[tool.ruff]
line-length = 100
""".strip(),
        encoding="utf-8",
    )

    recipe = detect_validation_recipe(str(project))

    assert recipe is not None
    assert recipe.recipe_id == "python"
    assert [check.kind for check in recipe.checks] == ["tests", "lint", "build"]


def test_detect_validation_recipe_uses_repo_local_override(tmp_path):
    from app.services.validation_recipe import detect_validation_recipe

    project = tmp_path / "custom-app"
    project.mkdir()
    (project / "package.json").write_text(
        json.dumps({"scripts": {"test": "vitest", "lint": "eslint .", "build": "vite build"}}),
        encoding="utf-8",
    )
    (project / ".codexmgr.validation.json").write_text(
        json.dumps(
            {
                "label": "Repo policy",
                "checks": [
                    {"kind": "tests", "label": "Smoke", "command": "./bin/smoke_test.sh"},
                    {"kind": "build", "label": "Package", "command": "npm run build", "required": False},
                ],
            }
        ),
        encoding="utf-8",
    )

    recipe = detect_validation_recipe(str(project))

    assert recipe is not None
    assert recipe.recipe_id == "custom-json"
    assert recipe.label == "Repo policy"
    assert [check.command for check in recipe.checks] == ["./bin/smoke_test.sh", "npm run build"]
    assert [check.required for check in recipe.checks] == [True, False]


def test_detect_validation_recipe_falls_back_when_override_invalid(tmp_path):
    from app.services.validation_recipe import detect_validation_recipe

    project = tmp_path / "fallback-app"
    project.mkdir()
    (project / "package.json").write_text(
        json.dumps({"scripts": {"test": "vitest", "lint": "eslint ."}}),
        encoding="utf-8",
    )
    (project / ".codexmgr.validation.json").write_text(
        json.dumps({"label": "Broken config", "checks": [{"kind": "tests"}]}),
        encoding="utf-8",
    )

    recipe = detect_validation_recipe(str(project))

    assert recipe is not None
    assert recipe.recipe_id == "node"
    assert [check.kind for check in recipe.checks] == ["tests", "lint"]


def test_detect_validation_recipe_uses_manager_preset_reference(tmp_path, monkeypatch):
    from app.services.validation_recipe import detect_validation_recipe

    codexmgr_home = tmp_path / ".codexmgr"
    codexmgr_home.mkdir()
    monkeypatch.setenv("CODEXMGR_HOME", str(codexmgr_home))
    (codexmgr_home / "validation-presets.json").write_text(
        json.dumps(
            {
                "presets": {
                    "strict-node": {
                        "label": "Strict Node",
                        "checks": [
                            {"kind": "tests", "label": "Tests", "command": "npm test"},
                            {"kind": "lint", "label": "Lint", "command": "npm run lint"},
                            {"kind": "build", "label": "Build", "command": "npm run build", "required": False},
                        ],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    project = tmp_path / "preset-app"
    project.mkdir()
    (project / "package.json").write_text(
        json.dumps({"scripts": {"test": "vitest"}}),
        encoding="utf-8",
    )
    (project / ".codexmgr.validation.json").write_text(
        json.dumps({"preset": "strict-node"}),
        encoding="utf-8",
    )

    recipe = detect_validation_recipe(str(project))

    assert recipe is not None
    assert recipe.recipe_id == "preset:strict-node"
    assert recipe.label == "Strict Node"
    assert [check.command for check in recipe.checks] == ["npm test", "npm run lint", "npm run build"]
    assert [check.required for check in recipe.checks] == [True, True, False]


def test_detect_validation_recipe_falls_back_when_preset_reference_is_missing(tmp_path, monkeypatch):
    from app.services.validation_recipe import detect_validation_recipe

    codexmgr_home = tmp_path / ".codexmgr"
    codexmgr_home.mkdir()
    monkeypatch.setenv("CODEXMGR_HOME", str(codexmgr_home))
    (codexmgr_home / "validation-presets.json").write_text(json.dumps({"presets": {}}), encoding="utf-8")

    project = tmp_path / "preset-fallback-app"
    project.mkdir()
    (project / "package.json").write_text(
        json.dumps({"scripts": {"test": "vitest", "lint": "eslint ."}}),
        encoding="utf-8",
    )
    (project / ".codexmgr.validation.json").write_text(
        json.dumps({"preset": "missing-preset"}),
        encoding="utf-8",
    )

    recipe = detect_validation_recipe(str(project))

    assert recipe is not None
    assert recipe.recipe_id == "node"
    assert [check.kind for check in recipe.checks] == ["tests", "lint"]


def test_list_manager_validation_presets_returns_normalized_presets(tmp_path, monkeypatch):
    from app.services.validation_recipe import list_manager_validation_presets

    codexmgr_home = tmp_path / ".codexmgr"
    codexmgr_home.mkdir()
    monkeypatch.setenv("CODEXMGR_HOME", str(codexmgr_home))
    (codexmgr_home / "validation-presets.json").write_text(
        json.dumps(
            {
                "presets": {
                    "strict-node": {
                        "label": "Strict Node",
                        "checks": [
                            {"kind": "tests", "label": "Tests", "command": "npm test"},
                            {"kind": "lint", "label": "Lint", "command": "npm run lint", "required": False},
                        ],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    rows = list_manager_validation_presets()

    assert rows == [
        {
            "id": "strict-node",
            "recipe_id": "preset:strict-node",
            "label": "Strict Node",
            "checks": [
                {"kind": "tests", "label": "Tests", "command": "npm test", "required": True},
                {"kind": "lint", "label": "Lint", "command": "npm run lint", "required": False},
            ],
        }
    ]


def test_missing_validation_checks_ignores_optional_checks():
    from app.services.validation_recipe import missing_validation_checks

    payload = json.dumps(
        {
            "label": "Repo policy",
            "checks": [
                {"kind": "tests", "label": "Tests", "command": "pytest"},
                {"kind": "lint", "label": "Lint", "command": "ruff check ."},
                {"kind": "build", "label": "Build", "command": "python -m build", "required": False},
            ],
        }
    )

    missing = missing_validation_checks(
        payload,
        test_status="passed",
        lint_status="unknown",
        build_status="unknown",
    )

    assert missing == ["lint"]


def test_validation_policy_state_distinguishes_required_and_optional_checks():
    from app.services.validation_recipe import validation_policy_state

    payload = json.dumps(
        {
            "label": "Repo policy",
            "checks": [
                {"kind": "tests", "label": "Tests", "command": "pytest"},
                {"kind": "lint", "label": "Lint", "command": "ruff check ."},
                {"kind": "build", "label": "Build", "command": "python -m build", "required": False},
            ],
        }
    )

    state, reason, missing, optional = validation_policy_state(
        payload,
        test_status="passed",
        lint_status="unknown",
        build_status="unknown",
    )
    assert state == "required_missing"
    assert reason == "required checks still missing: lint"
    assert missing == ["lint"]
    assert optional == ["build"]

    state, reason, missing, optional = validation_policy_state(
        payload,
        test_status="passed",
        lint_status="passed",
        build_status="unknown",
    )
    assert state == "optional_pending"
    assert reason == "optional checks still pending: build"
    assert missing == []
    assert optional == ["build"]

    state, reason, missing, optional = validation_policy_state(
        payload,
        test_status="passed",
        lint_status="passed",
        build_status="passed",
    )
    assert state == "ready"
    assert reason == "all required validation checks have been observed"
    assert missing == []
    assert optional == []


def test_materialize_validation_recipe_payload_keeps_effective_checks():
    from app.services.validation_recipe import materialize_validation_recipe_payload

    payload = json.dumps(
        {
            "label": "Repo policy",
            "checks": [
                {"kind": "tests", "label": "Smoke", "command": "./bin/smoke_test.sh"},
                {"kind": "lint", "label": "Lint", "command": "npm run lint", "required": False},
            ],
        }
    )

    result = materialize_validation_recipe_payload(payload)

    assert result == {
        "label": "Repo policy",
        "checks": [
            {"kind": "tests", "label": "Smoke", "command": "./bin/smoke_test.sh", "required": True},
            {"kind": "lint", "label": "Lint", "command": "npm run lint", "required": False},
        ],
    }

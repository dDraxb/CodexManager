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

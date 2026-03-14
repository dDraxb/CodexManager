from __future__ import annotations

import importlib
from pathlib import Path

import pytest


@pytest.fixture()
def configured_modules(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    home = tmp_path / "codexmgr-home"
    monkeypatch.setenv("CODEXMGR_HOME", str(home))

    from app.core import constants, settings
    from app.db import database
    from app.services import sessions

    importlib.reload(settings)
    importlib.reload(constants)
    importlib.reload(database)
    importlib.reload(sessions)

    return {
        "home": home,
        "database": database,
        "sessions": sessions,
    }


@pytest.fixture()
def git_repo(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("hello\n", encoding="utf-8")

    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    return repo

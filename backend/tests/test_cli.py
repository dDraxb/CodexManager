from __future__ import annotations

import importlib
import json

from typer.testing import CliRunner


runner = CliRunner()


def test_cli_lifecycle(configured_modules, git_repo):
    from app.cli import main as cli_main

    importlib.reload(cli_main)

    result = runner.invoke(
        cli_main.app,
        [
            "start",
            "--name",
            "vat-fix",
            "--repo",
            str(git_repo),
            "--profile",
            "safe-edit",
            "--create-worktree",
            "--no-launch",
        ],
    )
    assert result.exit_code == 0, result.output

    result = runner.invoke(cli_main.app, ["list", "--json"])
    assert result.exit_code == 0, result.output
    rows = json.loads(result.stdout)
    assert len(rows) == 1
    assert rows[0]["name"] == "vat-fix"
    assert rows[0]["worktree_path"] is not None

    result = runner.invoke(cli_main.app, ["inspect", "vat-fix"])
    assert result.exit_code == 0, result.output

    result = runner.invoke(cli_main.app, ["stop", "vat-fix"])
    assert result.exit_code == 0, result.output


def test_cli_adopt(configured_modules, git_repo):
    from app.cli import main as cli_main

    importlib.reload(cli_main)

    result = runner.invoke(
        cli_main.app,
        [
            "adopt",
            "--name",
            "imported-fix",
            "--codex-session",
            "cdx_123",
            "--repo",
            str(git_repo),
        ],
    )
    assert result.exit_code == 0, result.output

    result = runner.invoke(cli_main.app, ["inspect", "imported-fix"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["mode"] == "adopted"
    assert payload["observability"] == "reduced"


def test_cli_start_auto_init_git(configured_modules, tmp_path):
    from app.cli import main as cli_main

    importlib.reload(cli_main)

    folder = tmp_path / "plain-folder"
    folder.mkdir()
    (folder / "app.txt").write_text("hello\n", encoding="utf-8")

    result = runner.invoke(
        cli_main.app,
        [
            "start",
            "--name",
            "auto-init-fix",
            "--repo",
            str(folder),
            "--profile",
            "safe-edit",
            "--auto-init-git",
            "--no-launch",
        ],
    )
    assert result.exit_code == 0, result.output
    assert (folder / ".git").exists()


def test_cli_start_require_changelog(configured_modules, git_repo):
    from app.cli import main as cli_main

    importlib.reload(cli_main)

    result = runner.invoke(
        cli_main.app,
        [
          "start",
          "--name",
          "changelog-task",
          "--repo",
          str(git_repo),
          "--profile",
          "safe-edit",
          "--require-changelog",
          "--no-launch",
        ],
    )
    assert result.exit_code == 0, result.output
    changelog = git_repo / "CHANGELOG.md"
    assert changelog.exists()
    assert "changelog-task" in changelog.read_text(encoding="utf-8")


def test_cli_runner_command(configured_modules, monkeypatch):
    from app.cli import main as cli_main

    importlib.reload(cli_main)

    calls: list[tuple] = []

    def fake_run(app, host: str, port: int, log_level: str) -> None:
        calls.append((app.title, host, port, log_level))

    monkeypatch.setattr(cli_main.uvicorn, "run", fake_run)

    result = runner.invoke(cli_main.app, ["runner", "--host", "0.0.0.0", "--port", "8788"])

    assert result.exit_code == 0, result.output
    assert "Serving runner on http://0.0.0.0:8788" in result.stdout
    assert calls == [("codex-runner", "0.0.0.0", 8788, "info")]

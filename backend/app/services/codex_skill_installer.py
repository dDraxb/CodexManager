from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

from app.services.codex_skills import CodexSkillError, _skill_root

DEFAULT_SKILLS_REPO = "openai/skills"
DEFAULT_CURATED_PATH = "skills/.curated"
DEFAULT_EXPERIMENTAL_PATH = "skills/.experimental"
DEFAULT_REF = "main"
SKILL_INSTALLER_ROOT = Path.home() / ".codex" / "skills" / ".system" / "skill-installer"
LIST_SCRIPT = SKILL_INSTALLER_ROOT / "scripts" / "list-skills.py"
INSTALL_SCRIPT = SKILL_INSTALLER_ROOT / "scripts" / "install-skill-from-github.py"


class CodexSkillInstallError(RuntimeError):
    pass


def _installer_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(LIST_SCRIPT.parent)
    return env


def _run_installer(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        cmd,
        text=True,
        capture_output=True,
        check=False,
        env=_installer_env(),
        cwd=str(SKILL_INSTALLER_ROOT),
    )
    if proc.returncode != 0:
        message = proc.stderr.strip() or proc.stdout.strip() or "skill installer failed"
        raise CodexSkillInstallError(message)
    return proc


def _install_root(scope: str, repo_path: str | None) -> Path:
    try:
        return _skill_root(scope, repo_path)
    except CodexSkillError as exc:
        raise CodexSkillInstallError(str(exc)) from exc


def list_installable_codex_skills(
    *,
    scope: str,
    repo_path: str | None = None,
    repo: str = DEFAULT_SKILLS_REPO,
    path: str = DEFAULT_CURATED_PATH,
    ref: str = DEFAULT_REF,
) -> dict:
    proc = _run_installer(
        [
            "python3",
            str(LIST_SCRIPT),
            "--repo",
            repo,
            "--path",
            path,
            "--ref",
            ref,
            "--format",
            "json",
        ]
    )
    try:
        rows = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise CodexSkillInstallError("invalid skill list response") from exc
    if not isinstance(rows, list):
        raise CodexSkillInstallError("invalid skill list payload")

    install_root = _install_root(scope, repo_path)
    payload_rows: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        installed = (install_root / name / "SKILL.md").exists()
        payload_rows.append(
            {
                "name": name,
                "installed": installed,
                "source": {
                    "type": "catalog",
                    "repo": repo,
                    "path": f"{path.rstrip('/')}/{name}",
                    "ref": ref,
                },
            }
        )
    return {
        "scope": scope,
        "repoPath": repo_path,
        "repo": repo,
        "path": path,
        "ref": ref,
        "skills": payload_rows,
    }


def install_codex_skill_from_catalog(
    *,
    scope: str,
    name: str,
    repo_path: str | None = None,
    repo: str = DEFAULT_SKILLS_REPO,
    path: str = DEFAULT_CURATED_PATH,
    ref: str = DEFAULT_REF,
    method: str = "auto",
) -> dict:
    normalized_name = name.strip()
    if not normalized_name:
        raise CodexSkillInstallError("skill name is required")
    install_root = _install_root(scope, repo_path)
    install_root.mkdir(parents=True, exist_ok=True)
    source_path = f"{path.rstrip('/')}/{normalized_name}"
    _run_installer(
        [
            "python3",
            str(INSTALL_SCRIPT),
            "--repo",
            repo,
            "--path",
            source_path,
            "--ref",
            ref,
            "--dest",
            str(install_root),
            "--method",
            method,
        ]
    )
    return {
        "scope": scope,
        "name": normalized_name,
        "path": str(install_root / normalized_name),
        "skillFile": str(install_root / normalized_name / "SKILL.md"),
        "source": {
            "type": "catalog",
            "repo": repo,
            "path": source_path,
            "ref": ref,
            "method": method,
        },
    }


def install_codex_skill_from_github(
    *,
    scope: str,
    repo_path: str | None = None,
    github_repo: str | None = None,
    github_url: str | None = None,
    github_path: str | None = None,
    ref: str = DEFAULT_REF,
    method: str = "auto",
    name: str | None = None,
) -> dict:
    install_root = _install_root(scope, repo_path)
    install_root.mkdir(parents=True, exist_ok=True)
    cmd = [
        "python3",
        str(INSTALL_SCRIPT),
        "--dest",
        str(install_root),
        "--method",
        method,
    ]
    if name:
        cmd.extend(["--name", name.strip()])
    if github_url:
        cmd.extend(["--url", github_url.strip()])
        source_repo = github_url.strip()
    else:
        normalized_repo = str(github_repo or "").strip()
        normalized_path = str(github_path or "").strip()
        if not normalized_repo or not normalized_path:
            raise CodexSkillInstallError("github repo and path are required")
        cmd.extend(["--repo", normalized_repo, "--path", normalized_path, "--ref", ref])
        source_repo = normalized_repo
    _run_installer(cmd)
    installed_name = name.strip() if name and name.strip() else Path(str(github_path or github_url or "")).name
    if not installed_name:
        raise CodexSkillInstallError("unable to determine installed skill name")
    return {
        "scope": scope,
        "name": installed_name,
        "path": str(install_root / installed_name),
        "skillFile": str(install_root / installed_name / "SKILL.md"),
        "source": {
            "type": "github",
            "repo": source_repo,
            "path": github_path,
            "url": github_url,
            "ref": ref,
            "method": method,
        },
    }

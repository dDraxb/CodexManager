from __future__ import annotations

import importlib
import json

from fastapi.testclient import TestClient


def test_api_start_and_list(configured_modules, git_repo):
    from app.api import server

    importlib.reload(server)
    client = TestClient(server.app)

    response = client.post(
        "/api/sessions/start",
        json={
            "name": "api-vat-fix",
            "repoPath": str(git_repo),
            "profile": "safe-edit",
            "prompt": "Fix VAT",
            "createWorktreeForWrites": False,
            "launch": False,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["work_phase"] == "planning"
    assert response.json()["work_phase_confidence"] == "low"
    assert response.json()["last_major_phase"] == "planning"
    assert response.json()["last_major_phase_confidence"] == "low"
    assert response.json()["block_category"] is None
    assert response.json()["block_reason"] is None
    assert response.json()["health_label"] == "healthy"
    assert response.json()["priority_score"] == 46
    assert response.json()["repo_risk_label"] == "low"
    assert response.json()["review_readiness_state"] == "unknown"
    assert response.json()["completion_state"] == "unknown"

    response = client.get("/api/sessions")
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1

    sid = rows[0]["id"]
    assert rows[0]["work_phase"] == "planning"
    assert rows[0]["work_phase_confidence"] == "low"
    assert rows[0]["last_major_phase"] == "planning"
    assert rows[0]["last_major_phase_confidence"] == "low"
    assert rows[0]["status"] == "created"
    response = client.get(f"/api/sessions/{sid}")
    assert response.status_code == 200

    response = client.get("/api/summary")
    assert response.status_code == 200
    summary = response.json()
    assert summary["total"] == 1


def test_api_start_auto_init_git(configured_modules, tmp_path):
    from app.api import server

    importlib.reload(server)
    client = TestClient(server.app)

    folder = tmp_path / "plain-folder"
    folder.mkdir()
    (folder / "notes.txt").write_text("hello\n", encoding="utf-8")

    response = client.post(
        "/api/sessions/start",
        json={
            "name": "api-auto-init",
            "repoPath": str(folder),
            "profile": "safe-edit",
            "createWorktreeForWrites": True,
            "autoInitGit": True,
            "launch": False,
        },
    )
    assert response.status_code == 200, response.text
    assert (folder / ".git").exists()


def test_api_start_require_changelog(configured_modules, git_repo):
    from app.api import server

    importlib.reload(server)
    client = TestClient(server.app)

    response = client.post(
        "/api/sessions/start",
        json={
            "name": "api-changelog",
            "repoPath": str(git_repo),
            "profile": "safe-edit",
            "requireChangelog": True,
            "launch": False,
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["require_changelog"] == 1
    changelog = git_repo / "CHANGELOG.md"
    assert changelog.exists()
    assert "api-changelog" in changelog.read_text(encoding="utf-8")


def test_api_start_missing_path_returns_400(configured_modules):
    from app.api import server

    importlib.reload(server)
    client = TestClient(server.app)

    response = client.post(
        "/api/sessions/start",
        json={
            "name": "missing-path",
            "repoPath": "/definitely/not/here",
            "profile": "safe-edit",
            "launch": False,
        },
    )
    assert response.status_code == 400
    assert "working directory is not accessible" in response.text


def test_api_start_without_path_defaults_to_runner_home(configured_modules, tmp_path, monkeypatch):
    from app.api import server

    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))

    importlib.reload(server)
    client = TestClient(server.app)

    response = client.post(
        "/api/sessions/start",
        json={
            "name": "home-default",
            "profile": "safe-edit",
            "launch": False,
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["repo_path"] == str(home_dir.resolve())
    assert payload["cwd"] == str(home_dir.resolve())
    assert payload["target_label"] == "home"


def test_api_lists_validation_presets(configured_modules, tmp_path, monkeypatch):
    from app.api import server

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
                        ],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    importlib.reload(server)
    client = TestClient(server.app)

    response = client.get("/api/validation-presets")
    assert response.status_code == 200
    assert response.json()["presets"][0]["id"] == "strict-node"


def test_api_lists_codex_config_presets(configured_modules, tmp_path, monkeypatch):
    from app.api import server

    codexmgr_home = tmp_path / ".codexmgr"
    codexmgr_home.mkdir()
    monkeypatch.setenv("CODEXMGR_HOME", str(codexmgr_home))
    (codexmgr_home / "config-presets.json").write_text(
        json.dumps(
            {
                "presets": {
                    "safe-investigation": {
                        "label": "Safe Investigation",
                        "description": "Low-risk default config",
                        "content": 'model = "gpt-5.4"\npersonality = "pragmatic"\n',
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    importlib.reload(server)
    client = TestClient(server.app)

    response = client.get("/api/codex-config-presets")
    assert response.status_code == 200
    assert response.json()["presets"][0]["id"] == "safe-investigation"


def test_api_applies_codex_config_preset(configured_modules, tmp_path, monkeypatch):
    from app.api import server

    codexmgr_home = tmp_path / ".codexmgr"
    codexmgr_home.mkdir()
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    monkeypatch.setenv("CODEXMGR_HOME", str(codexmgr_home))
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    (codexmgr_home / "config-presets.json").write_text(
        json.dumps(
            {
                "presets": {
                    "safe-investigation": {
                        "label": "Safe Investigation",
                        "content": 'model = "gpt-5.4"\npersonality = "pragmatic"\n',
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    importlib.reload(server)
    client = TestClient(server.app)

    response = client.post(
        "/api/codex-config-presets/apply",
        json={"presetId": "safe-investigation", "scope": "global"},
    )
    assert response.status_code == 200, response.text
    assert (codex_home / "config.toml").read_text(encoding="utf-8") == 'model = "gpt-5.4"\npersonality = "pragmatic"\n'


def test_api_lists_repo_policies(configured_modules, tmp_path, monkeypatch):
    from app.api import server

    codexmgr_home = tmp_path / ".codexmgr"
    codexmgr_home.mkdir()
    monkeypatch.setenv("CODEXMGR_HOME", str(codexmgr_home))
    (codexmgr_home / "repo-policies.json").write_text(
        json.dumps(
            {
                "policies": {
                    "php-main-guard": {
                        "label": "PHP Main Guard",
                        "match": {"path_prefixes": ["/repo/service-a"]},
                        "rules": {"protected_branches": ["main"], "require_worktree_for_write": True},
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    importlib.reload(server)
    client = TestClient(server.app)

    response = client.get("/api/repo-policies")
    assert response.status_code == 200
    assert response.json()["policies"][0]["policy_id"] == "php-main-guard"


def test_api_returns_codex_environment(configured_modules, tmp_path, monkeypatch):
    from app.api import server

    codex_home = tmp_path / ".codex"
    repo = tmp_path / "repo"
    (codex_home / "skills" / "global-helper").mkdir(parents=True)
    (codex_home / "skills" / "global-helper" / "SKILL.md").write_text("# Global\n", encoding="utf-8")
    (codex_home / "config.toml").write_text("model = 'gpt-5.4'\n", encoding="utf-8")
    (repo / ".codex" / "skills" / "repo-helper").mkdir(parents=True)
    (repo / ".codex" / "skills" / "repo-helper" / "SKILL.md").write_text("# Repo\n", encoding="utf-8")
    (repo / ".codex" / "config.toml").write_text("sandbox = 'workspace-write'\n", encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    importlib.reload(server)
    client = TestClient(server.app)

    response = client.get("/api/codex-environment", params={"repo_path": str(repo)})
    assert response.status_code == 200
    payload = response.json()
    assert payload["globalConfig"]["exists"] is True
    assert payload["workspaceConfig"]["exists"] is True
    assert payload["globalSkills"][0]["name"] == "global-helper"
    assert payload["workspaceSkills"][0]["name"] == "repo-helper"


def test_api_creates_workspace_skill(configured_modules, tmp_path, monkeypatch):
    from app.api import server

    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / ".codex"))

    importlib.reload(server)
    client = TestClient(server.app)

    response = client.post(
        "/api/codex-skills",
        json={
            "scope": "workspace",
            "name": "release-guard",
            "summary": "Release checklist enforcement",
            "repoPath": str(repo),
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["scope"] == "workspace"
    assert (repo / ".codex" / "skills" / "release-guard" / "SKILL.md").exists()


def test_api_lists_installable_codex_skills(configured_modules, tmp_path, monkeypatch):
    from app.api import server
    from app.runner import client as runner_client

    repo = tmp_path / "repo"
    repo.mkdir()

    monkeypatch.setattr(
        runner_client,
        "list_installable_codex_skills",
        lambda **kwargs: {
            "scope": kwargs["scope"],
            "repoPath": kwargs["repo_path"],
            "repo": kwargs["repo"],
            "path": kwargs["path"],
            "ref": kwargs["ref"],
            "skills": [
                {
                    "name": "release-guard",
                    "installed": False,
                    "source": {
                        "type": "catalog",
                        "repo": kwargs["repo"],
                        "path": f"{kwargs['path']}/release-guard",
                        "ref": kwargs["ref"],
                    },
                }
            ],
        },
    )

    importlib.reload(server)
    client = TestClient(server.app)

    response = client.post(
        "/api/codex-skills/catalog",
        json={"scope": "workspace", "repoPath": str(repo), "path": "skills/.experimental"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["scope"] == "workspace"
    assert payload["path"] == "skills/.experimental"
    assert payload["skills"][0]["name"] == "release-guard"


def test_api_installs_codex_skill_from_github(configured_modules, tmp_path, monkeypatch):
    from app.api import server
    from app.runner import client as runner_client

    repo = tmp_path / "repo"
    repo.mkdir()

    def fake_install(**kwargs):
        root = repo / ".codex" / "skills" / "release-guard"
        root.mkdir(parents=True)
        (root / "SKILL.md").write_text("# Release Guard\n", encoding="utf-8")
        return {
            "scope": kwargs["scope"],
            "name": "release-guard",
            "path": str(root),
            "skillFile": str(root / "SKILL.md"),
            "source": {
                "type": "github",
                "repo": kwargs["github_repo"],
                "path": kwargs["github_path"],
                "url": kwargs["github_url"],
                "ref": kwargs["ref"],
                "method": kwargs["method"],
            },
        }

    monkeypatch.setattr(runner_client, "install_codex_skill_from_github", fake_install)

    importlib.reload(server)
    client = TestClient(server.app)

    response = client.post(
        "/api/codex-skills/install/github",
        json={
            "scope": "workspace",
            "repoPath": str(repo),
            "githubRepo": "example/skills",
            "githubPath": "skills/release-guard",
            "method": "download",
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["scope"] == "workspace"
    assert payload["name"] == "release-guard"
    assert payload["source"]["repo"] == "example/skills"
    assert (repo / ".codex" / "skills" / "release-guard" / "SKILL.md").exists()


def test_api_reads_and_writes_workspace_codex_config(configured_modules, tmp_path, monkeypatch):
    from app.api import server

    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / ".codex"))

    importlib.reload(server)
    client = TestClient(server.app)

    write_response = client.post(
        "/api/codex-config",
        json={
            "scope": "workspace",
            "content": "model = 'gpt-5.4'\n",
            "repoPath": str(repo),
        },
    )
    assert write_response.status_code == 200, write_response.text

    read_response = client.get(
        "/api/codex-config",
        params={"scope": "workspace", "repo_path": str(repo)},
    )
    assert read_response.status_code == 200
    payload = read_response.json()
    assert payload["exists"] is True
    assert "gpt-5.4" in payload["content"]

    second_write = client.post(
        "/api/codex-config",
        json={
            "scope": "workspace",
            "content": "model = 'gpt-5.3-codex'\n",
            "repoPath": str(repo),
        },
    )
    assert second_write.status_code == 200

    list_response = client.get(
        "/api/codex-config",
        params={"scope": "workspace", "repo_path": str(repo)},
    )
    backups = list_response.json()["backups"]
    assert backups

    restore_response = client.post(
        "/api/codex-config/restore",
        json={
            "scope": "workspace",
            "backupPath": backups[0]["path"],
            "repoPath": str(repo),
        },
    )
    assert restore_response.status_code == 200


def test_api_reads_and_writes_workspace_codex_rules(configured_modules, tmp_path, monkeypatch):
    from app.api import server

    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / ".codex"))

    importlib.reload(server)
    client = TestClient(server.app)

    write_response = client.post(
        "/api/codex-rules",
        json={
            "scope": "workspace",
            "content": "# Repo Rules\n\n- Always run tests.\n",
            "repoPath": str(repo),
        },
    )
    assert write_response.status_code == 200, write_response.text

    read_response = client.get(
        "/api/codex-rules",
        params={"scope": "workspace", "repo_path": str(repo)},
    )
    assert read_response.status_code == 200
    payload = read_response.json()
    assert payload["exists"] is True
    assert "Always run tests" in payload["content"]

    second_write = client.post(
        "/api/codex-rules",
        json={
            "scope": "workspace",
            "content": "# Repo Rules\n\n- Run lint too.\n",
            "repoPath": str(repo),
        },
    )
    assert second_write.status_code == 200

    list_response = client.get(
        "/api/codex-rules",
        params={"scope": "workspace", "repo_path": str(repo)},
    )
    backups = list_response.json()["backups"]
    assert backups

    restore_response = client.post(
        "/api/codex-rules/restore",
        json={
            "scope": "workspace",
            "backupPath": backups[0]["path"],
            "repoPath": str(repo),
        },
    )
    assert restore_response.status_code == 200


def test_api_reads_writes_and_restores_manager_rules(configured_modules, tmp_path, monkeypatch):
    from app.api import server

    codexmgr_home = tmp_path / ".codexmgr"
    codexmgr_home.mkdir()
    monkeypatch.setenv("CODEXMGR_HOME", str(codexmgr_home))

    importlib.reload(server)
    client = TestClient(server.app)

    read_response = client.get("/api/manager-rules")
    assert read_response.status_code == 200
    assert read_response.json()["exists"] is False

    write_response = client.post(
        "/api/manager-rules",
        json={
            "content": json.dumps(
                {
                    "version": 1,
                    "rules": [
                        {
                            "id": "preferred-skills",
                            "label": "Preferred skills",
                            "category": "skills",
                            "enabled": True,
                            "scope": {"level": "global"},
                            "content": {"preferred": ["openai-docs", "imagegen"]},
                        }
                    ],
                }
            )
        },
    )
    assert write_response.status_code == 200, write_response.text
    assert write_response.json()["ruleCount"] == 1

    second_write = client.post(
        "/api/manager-rules",
        json={
            "content": json.dumps(
                {
                    "version": 1,
                    "rules": [
                        {
                            "id": "preferred-skills",
                            "label": "Preferred skills",
                            "category": "skills",
                            "enabled": False,
                            "scope": {"level": "global"},
                            "content": {"preferred": ["openai-docs"]},
                        }
                    ],
                }
            )
        },
    )
    assert second_write.status_code == 200, second_write.text

    list_response = client.get("/api/manager-rules")
    assert list_response.status_code == 200
    payload = list_response.json()
    assert payload["exists"] is True
    assert payload["valid"] is True
    assert payload["ruleCount"] == 1
    assert payload["rules"][0]["id"] == "preferred-skills"
    backups = payload["backups"]
    assert backups

    restore_response = client.post(
        "/api/manager-rules/restore",
        json={"backupPath": backups[0]["path"]},
    )
    assert restore_response.status_code == 200


def test_api_rejects_invalid_manager_rules(configured_modules):
    from app.api import server

    importlib.reload(server)
    client = TestClient(server.app)

    response = client.post(
        "/api/manager-rules",
        json={
            "content": json.dumps(
                {
                    "version": 1,
                    "rules": [
                        {
                            "id": "broken",
                            "enabled": "yes",
                            "content": {"mode": "strict"},
                        }
                    ],
                }
            )
        },
    )
    assert response.status_code == 400
    assert "expected boolean" in response.text


def test_api_returns_effective_manager_rule_session_defaults(configured_modules, tmp_path, monkeypatch):
    from app.api import server

    codexmgr_home = tmp_path / ".codexmgr"
    codexmgr_home.mkdir()
    monkeypatch.setenv("CODEXMGR_HOME", str(codexmgr_home))
    (codexmgr_home / "manager-rules.json").write_text(
        json.dumps(
            {
                "version": 1,
                "rules": [
                    {
                        "id": "global-defaults",
                        "category": "session_defaults",
                        "scope": {"level": "global"},
                        "content": {
                            "profile": "safe-edit",
                            "approval_policy": "on-request",
                            "launch": True,
                        },
                    },
                    {
                        "id": "repo-defaults",
                        "category": "session_defaults",
                        "scope": {"level": "workspace", "repo_path": "/repo/service-a"},
                        "content": {
                            "profile": "full-agent",
                            "create_worktree_for_writes": True,
                            "require_changelog": True,
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    importlib.reload(server)
    client = TestClient(server.app)

    response = client.get(
        "/api/manager-rules/effective-session-defaults",
        params={"repo_path": "/repo/service-a/api"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["defaults"]["profile"] == "full-agent"
    assert payload["defaults"]["approvalPolicy"] == "on-request"
    assert payload["defaults"]["createWorktreeForWrites"] is True
    assert payload["defaults"]["requireChangelog"] is True
    assert [row["id"] for row in payload["appliedRules"]] == ["global-defaults", "repo-defaults"]


def test_api_returns_manager_rule_match_preview(configured_modules, tmp_path, monkeypatch):
    from app.api import server

    codexmgr_home = tmp_path / ".codexmgr"
    codexmgr_home.mkdir()
    monkeypatch.setenv("CODEXMGR_HOME", str(codexmgr_home))
    (codexmgr_home / "manager-rules.json").write_text(
        json.dumps(
            {
                "version": 1,
                "rules": [
                    {
                        "id": "global-defaults",
                        "label": "Global defaults",
                        "category": "session_defaults",
                        "scope": {"level": "global"},
                        "content": {
                            "profile": "safe-edit",
                            "launch": True,
                        },
                    },
                    {
                        "id": "repo-skill-preferences",
                        "label": "Repo skill preferences",
                        "category": "skills",
                        "scope": {"level": "workspace", "repo_path": "/repo/service-a"},
                        "content": {
                            "preferred": ["openai-docs"],
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    importlib.reload(server)
    client = TestClient(server.app)

    response = client.get(
        "/api/manager-rules/matches",
        params={"repo_path": "/repo/service-a/api"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["repoPath"] == "/repo/service-a/api"
    assert payload["presetId"] == ""
    assert [row["id"] for row in payload["matchedRules"]] == [
        "global-defaults",
        "repo-skill-preferences",
    ]
    assert payload["effectiveSessionDefaults"]["defaults"]["profile"] == "safe-edit"


def test_api_lists_and_creates_codex_agents(configured_modules, tmp_path, monkeypatch):
    from app.api import server

    codex_home = tmp_path / ".codex"
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    importlib.reload(server)
    client = TestClient(server.app)

    create_response = client.post(
        "/api/codex-agents",
        json={
            "name": "release-captain",
            "summary": "Release-focused helper",
        },
    )
    assert create_response.status_code == 200, create_response.text

    list_response = client.get("/api/codex-agents")
    assert list_response.status_code == 200
    payload = list_response.json()
    assert payload["agents"][0]["name"] == "release-captain"


def test_api_lists_and_creates_codex_mcp_servers(configured_modules, tmp_path, monkeypatch):
    from app.api import server

    codex_home = tmp_path / ".codex"
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    importlib.reload(server)
    client = TestClient(server.app)

    create_response = client.post(
        "/api/codex-mcp",
        json={
            "scope": "global",
            "name": "firefox-devtools",
            "command": "npx",
            "args": ["@padenot/firefox-devtools-mcp"],
        },
    )
    assert create_response.status_code == 200, create_response.text

    list_response = client.get("/api/codex-mcp", params={"scope": "global"})
    assert list_response.status_code == 200
    payload = list_response.json()
    assert payload["servers"][0]["name"] == "firefox-devtools"

    update_response = client.post(
        "/api/codex-mcp/update",
        json={
            "scope": "global",
            "name": "firefox-devtools",
            "command": "node",
            "args": ["server.js"],
        },
    )
    assert update_response.status_code == 200, update_response.text

    list_response = client.get("/api/codex-mcp", params={"scope": "global"})
    assert list_response.status_code == 200
    payload = list_response.json()
    assert payload["servers"][0]["command"] == "node"
    assert payload["servers"][0]["args"] == ["server.js"]
    assert payload["servers"][0]["enabled"] is True

    disable_response = client.post(
        "/api/codex-mcp/enabled",
        json={
            "scope": "global",
            "name": "firefox-devtools",
            "enabled": False,
        },
    )
    assert disable_response.status_code == 200, disable_response.text

    list_response = client.get("/api/codex-mcp", params={"scope": "global"})
    assert list_response.status_code == 200
    payload = list_response.json()
    assert payload["servers"][0]["enabled"] is False

    enable_response = client.post(
        "/api/codex-mcp/enabled",
        json={
            "scope": "global",
            "name": "firefox-devtools",
            "enabled": True,
        },
    )
    assert enable_response.status_code == 200, enable_response.text

    list_response = client.get("/api/codex-mcp", params={"scope": "global"})
    assert list_response.status_code == 200
    payload = list_response.json()
    assert payload["servers"][0]["enabled"] is True

    delete_response = client.post(
        "/api/codex-mcp/delete",
        json={
            "scope": "global",
            "name": "firefox-devtools",
        },
    )
    assert delete_response.status_code == 200, delete_response.text

    list_response = client.get("/api/codex-mcp", params={"scope": "global"})
    assert list_response.status_code == 200
    assert list_response.json()["servers"] == []


def test_api_reads_and_writes_codex_agent_config(configured_modules, tmp_path, monkeypatch):
    from app.api import server

    codex_home = tmp_path / ".codex"
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    importlib.reload(server)
    client = TestClient(server.app)

    create_response = client.post(
        "/api/codex-agents",
        json={
            "name": "quality-helper",
            "summary": "Quality helper",
        },
    )
    assert create_response.status_code == 200, create_response.text

    read_response = client.get("/api/codex-agent-config", params={"name": "quality-helper"})
    assert read_response.status_code == 200, read_response.text
    payload = read_response.json()
    assert payload["name"] == "quality-helper"
    assert 'model = "gpt-5.4"' in payload["content"]

    write_response = client.post(
        "/api/codex-agent-config",
        json={
            "name": "quality-helper",
            "content": '# Updated\n\nmodel = "gpt-5.4"\n',
        },
    )
    assert write_response.status_code == 200, write_response.text

    read_response = client.get("/api/codex-agent-config", params={"name": "quality-helper"})
    assert read_response.status_code == 200, read_response.text
    payload = read_response.json()
    assert payload["content"].startswith("# Updated")
    assert payload["backups"]

    restore_response = client.post(
        "/api/codex-agent-config/restore",
        json={
            "name": "quality-helper",
            "backupPath": payload["backups"][0]["path"],
        },
    )
    assert restore_response.status_code == 200, restore_response.text

    read_response = client.get("/api/codex-agent-config", params={"name": "quality-helper"})
    assert read_response.status_code == 200, read_response.text
    assert 'description = "Quality helper"' in read_response.json()["content"]


def test_api_reads_writes_and_deletes_codex_skill(configured_modules, tmp_path, monkeypatch):
    from app.api import server

    codex_home = tmp_path / ".codex"
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    importlib.reload(server)
    client = TestClient(server.app)

    create_response = client.post(
        "/api/codex-skills",
        json={
            "scope": "workspace",
            "name": "release-guard",
            "summary": "Guard release changes",
            "repoPath": str(repo),
        },
    )
    assert create_response.status_code == 200, create_response.text

    read_response = client.get(
        "/api/codex-skill",
        params={"scope": "workspace", "name": "release-guard", "repo_path": str(repo)},
    )
    assert read_response.status_code == 200, read_response.text
    payload = read_response.json()
    assert payload["name"] == "release-guard"
    assert "## Purpose" in payload["content"]

    write_response = client.post(
        "/api/codex-skill",
        json={
            "scope": "workspace",
            "name": "release-guard",
            "content": "# Updated skill\n",
            "repoPath": str(repo),
        },
    )
    assert write_response.status_code == 200, write_response.text

    read_response = client.get(
        "/api/codex-skill",
        params={"scope": "workspace", "name": "release-guard", "repo_path": str(repo)},
    )
    assert read_response.status_code == 200, read_response.text
    payload = read_response.json()
    assert payload["content"].startswith("# Updated skill")
    assert payload["backups"]

    restore_response = client.post(
        "/api/codex-skill/restore",
        json={
            "scope": "workspace",
            "name": "release-guard",
            "backupPath": payload["backups"][0]["path"],
            "repoPath": str(repo),
        },
    )
    assert restore_response.status_code == 200, restore_response.text

    read_response = client.get(
        "/api/codex-skill",
        params={"scope": "workspace", "name": "release-guard", "repo_path": str(repo)},
    )
    assert read_response.status_code == 200, read_response.text
    assert "## Purpose" in read_response.json()["content"]

    delete_response = client.post(
        "/api/codex-skill/delete",
        json={
            "scope": "workspace",
            "name": "release-guard",
            "repoPath": str(repo),
        },
    )
    assert delete_response.status_code == 200, delete_response.text

    read_response = client.get(
        "/api/codex-skill",
        params={"scope": "workspace", "name": "release-guard", "repo_path": str(repo)},
    )
    assert read_response.status_code == 200, read_response.text
    assert read_response.json()["exists"] is False


def test_api_reads_writes_and_deletes_codex_prompt(configured_modules, tmp_path, monkeypatch):
    from app.api import server

    codex_home = tmp_path / ".codex"
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    importlib.reload(server)
    client = TestClient(server.app)

    create_response = client.post(
        "/api/codex-prompts",
        json={
            "scope": "workspace",
            "name": "safe-investigation",
            "content": "# Safe investigation\n",
            "repoPath": str(repo),
        },
    )
    assert create_response.status_code == 200, create_response.text

    read_response = client.get(
        "/api/codex-prompt",
        params={"scope": "workspace", "name": "safe-investigation", "repo_path": str(repo)},
    )
    assert read_response.status_code == 200, read_response.text
    payload = read_response.json()
    assert payload["name"] == "safe-investigation"
    assert payload["content"].startswith("# Safe investigation")

    write_response = client.post(
        "/api/codex-prompt",
        json={
            "scope": "workspace",
            "name": "safe-investigation",
            "content": "# Updated prompt\n",
            "repoPath": str(repo),
        },
    )
    assert write_response.status_code == 200, write_response.text

    read_response = client.get(
        "/api/codex-prompt",
        params={"scope": "workspace", "name": "safe-investigation", "repo_path": str(repo)},
    )
    assert read_response.status_code == 200, read_response.text
    payload = read_response.json()
    assert payload["content"].startswith("# Updated prompt")
    assert payload["backups"]

    restore_response = client.post(
        "/api/codex-prompt/restore",
        json={
            "scope": "workspace",
            "name": "safe-investigation",
            "backupPath": payload["backups"][0]["path"],
            "repoPath": str(repo),
        },
    )
    assert restore_response.status_code == 200, restore_response.text

    read_response = client.get(
        "/api/codex-prompt",
        params={"scope": "workspace", "name": "safe-investigation", "repo_path": str(repo)},
    )
    assert read_response.status_code == 200, read_response.text
    assert read_response.json()["content"].startswith("# Safe investigation")

    delete_response = client.post(
        "/api/codex-prompt/delete",
        json={
            "scope": "workspace",
            "name": "safe-investigation",
            "repoPath": str(repo),
        },
    )
    assert delete_response.status_code == 200, delete_response.text

    prompt_list_response = client.get("/api/codex-prompts", params={"scope": "workspace", "repo_path": str(repo)})
    assert prompt_list_response.status_code == 200, prompt_list_response.text
    assert prompt_list_response.json()["prompts"] == []


def test_api_previews_and_validates_codex_config(configured_modules, tmp_path, monkeypatch):
    from app.api import server

    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    (codex_home / "config.toml").write_text('model = "gpt-5.4"\n', encoding="utf-8")

    importlib.reload(server)
    client = TestClient(server.app)

    preview_response = client.post(
        "/api/codex-config/preview",
        json={
            "scope": "global",
            "content": 'model = "gpt-5.4"\npersonality = "pragmatic"\n',
        },
    )
    assert preview_response.status_code == 200, preview_response.text
    payload = preview_response.json()
    assert payload["valid"] is True
    assert any(line.startswith("+personality") for line in payload["diff"])

    invalid_response = client.post(
        "/api/codex-config",
        json={
            "scope": "global",
            "content": '[broken\nvalue = "x"\n',
        },
    )
    assert invalid_response.status_code == 400
    assert "invalid TOML" in invalid_response.text


def test_api_start_applies_repo_policy_enforcement(configured_modules, git_repo, tmp_path, monkeypatch):
    from app.api import server

    codexmgr_home = tmp_path / ".codexmgr"
    codexmgr_home.mkdir()
    monkeypatch.setenv("CODEXMGR_HOME", str(codexmgr_home))
    (codexmgr_home / "repo-policies.json").write_text(
        json.dumps(
            {
                "policies": {
                    "php-main-guard": {
                        "label": "PHP Main Guard",
                        "match": {"path_prefixes": [str(git_repo)]},
                        "rules": {"protected_branches": ["main"], "require_worktree_for_write": True},
                        "defaults": {"require_changelog": True, "approval_policy": "never"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    importlib.reload(server)
    client = TestClient(server.app)

    response = client.post(
        "/api/sessions/start",
        json={
            "name": "policy-enforced",
            "repoPath": str(git_repo),
            "profile": "safe-edit",
            "createWorktreeForWrites": False,
            "requireChangelog": False,
            "launch": False,
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["repo_policy_id"] == "php-main-guard"
    assert payload["approval_policy"] == "never"
    assert payload["require_changelog"] == 1
    assert payload["worktree_path"]
    assert payload["cwd"] == payload["worktree_path"]


def test_api_start_applies_selected_manager_defaults(configured_modules, git_repo, tmp_path, monkeypatch):
    from app.api import server

    codexmgr_home = tmp_path / ".codexmgr"
    codexmgr_home.mkdir()
    monkeypatch.setenv("CODEXMGR_HOME", str(codexmgr_home))
    (codexmgr_home / "manager-rules.json").write_text(
        json.dumps(
            {
                "version": 1,
                "rules": [
                    {
                        "id": "repo-session-defaults",
                        "label": "Repo session defaults",
                        "category": "session_defaults",
                        "scope": {"level": "workspace", "repo_path": str(git_repo)},
                        "content": {
                            "profile": "full-agent",
                            "approval_policy": "never",
                            "create_worktree_for_writes": True,
                            "require_changelog": True,
                            "launch": False,
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    importlib.reload(server)
    client = TestClient(server.app)

    response = client.post(
        "/api/sessions/start",
        json={
            "name": "manager-defaults-enforced",
            "repoPath": str(git_repo),
            "profile": "safe-edit",
            "approvalPolicy": "on-request",
            "createWorktreeForWrites": False,
            "requireChangelog": False,
            "launch": True,
            "managerDefaultsFields": [
                "profile",
                "approvalPolicy",
                "createWorktreeForWrites",
                "requireChangelog",
                "launch",
            ],
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["profile"] == "full-agent"
    assert payload["approval_policy"] == "never"
    assert payload["require_changelog"] == 1
    assert payload["worktree_path"]
    assert payload["cwd"] == payload["worktree_path"]
    assert payload["status"] == "created"


def test_api_start_respects_user_overrides_outside_selected_manager_defaults(configured_modules, git_repo, tmp_path, monkeypatch):
    from app.api import server

    codexmgr_home = tmp_path / ".codexmgr"
    codexmgr_home.mkdir()
    monkeypatch.setenv("CODEXMGR_HOME", str(codexmgr_home))
    (codexmgr_home / "manager-rules.json").write_text(
        json.dumps(
            {
                "version": 1,
                "rules": [
                    {
                        "id": "repo-session-defaults",
                        "label": "Repo session defaults",
                        "category": "session_defaults",
                        "scope": {"level": "workspace", "repo_path": str(git_repo)},
                        "content": {
                            "profile": "full-agent",
                            "approval_policy": "never",
                            "create_worktree_for_writes": True,
                            "require_changelog": True,
                            "launch": False,
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    importlib.reload(server)
    client = TestClient(server.app)

    response = client.post(
        "/api/sessions/start",
        json={
            "name": "manager-defaults-partial",
            "repoPath": str(git_repo),
            "profile": "safe-edit",
            "approvalPolicy": "on-request",
            "createWorktreeForWrites": False,
            "requireChangelog": False,
            "launch": True,
            "managerDefaultsFields": ["approvalPolicy"],
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["profile"] == "safe-edit"
    assert payload["approval_policy"] == "never"
    assert payload["require_changelog"] == 0
    assert payload["worktree_path"] is None
    assert payload["cwd"] == str(git_repo.resolve())
    assert payload["status"] == "starting"


def test_api_applies_validation_preset(configured_modules, tmp_path, monkeypatch):
    from app.api import server

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
                        ],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    project = tmp_path / "preset-target"
    project.mkdir()

    importlib.reload(server)
    client = TestClient(server.app)

    response = client.post(
        "/api/validation-presets/apply",
        json={"repoPath": str(project), "presetId": "strict-node"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["configPath"].endswith(".codexmgr.validation.json")
    assert json.loads((project / ".codexmgr.validation.json").read_text(encoding="utf-8")) == {"preset": "strict-node"}


def test_api_materializes_validation_recipe(configured_modules, tmp_path):
    from app.api import server

    project = tmp_path / "recipe-target"
    project.mkdir()

    importlib.reload(server)
    client = TestClient(server.app)

    response = client.post(
        "/api/validation-recipes/materialize",
        json={
            "repoPath": str(project),
            "recipeJson": json.dumps(
                {
                    "label": "Repo policy",
                    "checks": [
                        {"kind": "tests", "label": "Smoke", "command": "./bin/smoke_test.sh"},
                        {"kind": "lint", "label": "Lint", "command": "npm run lint", "required": False},
                    ],
                }
            ),
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["configPath"].endswith(".codexmgr.validation.json")
    assert json.loads((project / ".codexmgr.validation.json").read_text(encoding="utf-8")) == {
        "label": "Repo policy",
        "checks": [
            {"kind": "tests", "label": "Smoke", "command": "./bin/smoke_test.sh", "required": True},
            {"kind": "lint", "label": "Lint", "command": "npm run lint", "required": False},
        ],
    }


def test_api_delete_session(configured_modules, git_repo):
    from app.api import server

    importlib.reload(server)
    client = TestClient(server.app)

    response = client.post(
        "/api/sessions/start",
        json={
            "name": "delete-me",
            "repoPath": str(git_repo),
            "profile": "read-only",
            "launch": False,
        },
    )
    assert response.status_code == 200
    session_id = response.json()["id"]

    response = client.delete(f"/api/sessions/{session_id}")
    assert response.status_code == 200

    response = client.get("/api/sessions")
    assert response.status_code == 200
    assert response.json() == []


def test_api_delete_adopted_session_remains_deleted_after_summary(configured_modules, git_repo):
    from app.api import server

    importlib.reload(server)
    client = TestClient(server.app)

    response = client.post(
        "/api/sessions/adopt",
        json={
            "name": "delete-adopted",
            "codexSessionId": "019ce115-d070-7053-b385-870d5e021ea7",
            "repoPath": str(git_repo),
            "profile": "read-only",
        },
    )
    assert response.status_code == 200, response.text
    session_id = response.json()["id"]

    response = client.delete(f"/api/sessions/{session_id}")
    assert response.status_code == 200, response.text

    response = client.get("/api/summary")
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 0

    response = client.get("/api/sessions")
    assert response.status_code == 200
    assert response.json() == []


def test_api_bulk_delete_endpoints(configured_modules, git_repo):
    from app.api import server

    importlib.reload(server)
    client = TestClient(server.app)

    stopped = client.post(
        "/api/sessions/start",
        json={
            "name": "stopped-one",
            "repoPath": str(git_repo),
            "profile": "read-only",
            "launch": False,
        },
    )
    assert stopped.status_code == 200
    stopped_id = stopped.json()["id"]
    response = client.post(f"/api/sessions/{stopped_id}/stop")
    assert response.status_code == 200

    test_named = client.post(
        "/api/sessions/start",
        json={
            "name": "test-cleanup",
            "repoPath": str(git_repo),
            "profile": "read-only",
            "launch": False,
        },
    )
    assert test_named.status_code == 200

    response = client.post("/api/sessions/bulk-delete/stopped")
    assert response.status_code == 200
    assert response.json()["count"] == 1

    response = client.post("/api/sessions/bulk-delete/test-named")
    assert response.status_code == 200
    assert response.json()["count"] == 1


def test_api_logs_uses_runner_pane_for_running_sessions(configured_modules, git_repo):
    from app.api import server

    importlib.reload(server)
    client = TestClient(server.app)
    response = client.post(
        "/api/sessions/start",
        json={
            "name": "log-pane",
            "repoPath": str(git_repo),
            "profile": "read-only",
            "launch": False,
        },
    )
    assert response.status_code == 200, response.text
    session_id = response.json()["id"]
    server.capture_session_logs = lambda sid, tail=200: ["pane line"] if sid == session_id else []

    response = client.get(f"/api/sessions/{session_id}/logs")

    assert response.status_code == 200
    assert response.json()["lines"] == ["pane line"]


def test_api_open_adopted_session_requires_resume_first(configured_modules, git_repo):
    from app.api import server

    importlib.reload(server)
    client = TestClient(server.app)

    response = client.post(
        "/api/sessions/adopt",
        json={
            "name": "api-adopted",
            "codexSessionId": "cdx_123",
            "repoPath": str(git_repo),
            "profile": "read-only",
        },
    )
    assert response.status_code == 200, response.text
    session_id = response.json()["id"]

    response = client.post(f"/api/sessions/{session_id}/open")

    assert response.status_code == 400
    assert "use Resume first" in response.text


def test_api_summary_triggers_reconciliation(configured_modules, monkeypatch):
    from app.api import server

    importlib.reload(server)
    client = TestClient(server.app)

    calls = []
    monkeypatch.setattr(server, "reconcile_once", lambda: calls.append("reconciled") or 1)

    response = client.get("/api/summary")

    assert response.status_code == 200
    assert calls == ["reconciled"]


def test_api_sessions_list_triggers_reconciliation(configured_modules, monkeypatch):
    from app.api import server

    importlib.reload(server)
    client = TestClient(server.app)

    class ImmediateThread:
        def __init__(self, *, target, daemon):
            self._target = target

        def start(self):
            self._target()

    calls = []
    monkeypatch.setattr(server, "reconcile_once", lambda: calls.append("reconciled") or 1)
    monkeypatch.setattr(server.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(server, "_last_reconcile_monotonic", 0.0)

    response = client.get("/api/sessions")

    assert response.status_code == 200
    assert calls == ["reconciled"]


def test_api_session_detail_triggers_reconciliation(configured_modules, git_repo, monkeypatch):
    from app.api import server

    importlib.reload(server)
    client = TestClient(server.app)

    create_response = client.post(
        "/api/sessions/start",
        json={
            "name": "detail-reconcile-api",
            "repoPath": str(git_repo),
            "profile": "safe-edit",
            "launch": False,
        },
    )
    assert create_response.status_code == 200, create_response.text
    session_id = create_response.json()["id"]

    class ImmediateThread:
        def __init__(self, *, target, daemon):
            self._target = target

        def start(self):
            self._target()

    calls = []
    monkeypatch.setattr(server, "reconcile_once", lambda: calls.append("reconciled") or 1)
    monkeypatch.setattr(server.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(server, "_last_reconcile_monotonic", 0.0)

    response = client.get(f"/api/sessions/{session_id}")

    assert response.status_code == 200
    assert calls == ["reconciled"]


def test_api_session_endpoints_throttle_immediate_reconciliation(configured_modules, git_repo, monkeypatch):
    from app.api import server

    importlib.reload(server)
    client = TestClient(server.app)

    create_response = client.post(
        "/api/sessions/start",
        json={
            "name": "reconcile-throttle-api",
            "repoPath": str(git_repo),
            "profile": "safe-edit",
            "launch": False,
        },
    )
    assert create_response.status_code == 200, create_response.text
    session_id = create_response.json()["id"]

    class ImmediateThread:
        def __init__(self, *, target, daemon):
            self._target = target

        def start(self):
            self._target()

    calls = []
    monkeypatch.setattr(server, "reconcile_once", lambda: calls.append("reconciled") or 1)
    monkeypatch.setattr(server.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(server, "_last_reconcile_monotonic", 0.0)

    list_response = client.get("/api/sessions")
    detail_response = client.get(f"/api/sessions/{session_id}")

    assert list_response.status_code == 200
    assert detail_response.status_code == 200
    assert calls == ["reconciled"]


def test_api_health_is_lightweight(configured_modules, monkeypatch):
    from app.api import server

    importlib.reload(server)
    client = TestClient(server.app)

    def fail_reconcile():
        raise AssertionError("health endpoint should not reconcile")

    monkeypatch.setattr(server, "reconcile_once", fail_reconcile)

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_api_resume_points_uses_runner_history(configured_modules, git_repo, monkeypatch):
    from app.api import server

    importlib.reload(server)
    client = TestClient(server.app)

    response = client.post(
        "/api/sessions/start",
        json={
            "name": "resume-points-api",
            "repoPath": str(git_repo),
            "profile": "safe-edit",
            "prompt": "Refactor service layer",
            "launch": False,
        },
    )
    assert response.status_code == 200, response.text
    session_id = response.json()["id"]

    class HistoryRunner:
        def list_resume_candidates(self, thread_id, cwd, prompt, limit=12):
            assert thread_id is None
            assert cwd == str(git_repo)
            assert prompt == "Refactor service layer"
            return [{"id": "019ce115-d070-7053-b385-870d5e021ea7", "cwd": cwd, "created_at": 1, "updated_at": 2, "title": prompt, "first_user_message": prompt, "rollout_path": "rollout.jsonl"}]

    monkeypatch.setattr(server, "get_runner_client", lambda: HistoryRunner())

    response = client.get(f"/api/sessions/{session_id}/resume-points")

    assert response.status_code == 200
    assert response.json()["threads"][0]["id"] == "019ce115-d070-7053-b385-870d5e021ea7"


def test_api_codex_resume_points_uses_explicit_thread_id(configured_modules, monkeypatch):
    from app.api import server

    importlib.reload(server)
    client = TestClient(server.app)

    class HistoryRunner:
        def list_resume_candidates(self, thread_id, cwd, prompt, limit=12):
            assert thread_id == "019cf8f7-ee18-7e81-9683-4e3fc2008c79"
            assert cwd == "/repo/service-a"
            assert prompt is None
            return [{"id": thread_id, "cwd": cwd, "created_at": 1, "updated_at": 2, "title": "proof", "first_user_message": "proof", "rollout_path": "rollout.jsonl"}]

    monkeypatch.setattr(server, "get_runner_client", lambda: HistoryRunner())

    response = client.get(
        "/api/codex/resume-points?thread_id=019cf8f7-ee18-7e81-9683-4e3fc2008c79&cwd=/repo/service-a"
    )

    assert response.status_code == 200
    assert response.json()["threads"][0]["id"] == "019cf8f7-ee18-7e81-9683-4e3fc2008c79"


def test_api_codex_history_uses_repo_path_filter(configured_modules, monkeypatch):
    from app.api import server

    importlib.reload(server)
    client = TestClient(server.app)

    class HistoryRunner:
        def list_codex_threads(self, cwd, query, limit=20):
            assert cwd == "/repo/service-a"
            assert query == ""
            return [
                {
                    "id": "019cf8f7-ee18-7e81-9683-4e3fc2008c79",
                    "cwd": cwd,
                    "created_at": 1,
                    "updated_at": 2,
                    "title": "proof",
                    "first_user_message": "proof",
                    "rollout_path": "rollout.jsonl",
                }
            ]

    monkeypatch.setattr(server, "get_runner_client", lambda: HistoryRunner())

    response = client.get("/api/codex/history?cwd=/repo/service-a&query=")

    assert response.status_code == 200
    assert response.json()["threads"][0]["cwd"] == "/repo/service-a"


def test_api_can_update_codex_session_link(configured_modules, git_repo):
    from app.api import server

    importlib.reload(server)
    client = TestClient(server.app)

    response = client.post(
        "/api/sessions/start",
        json={
            "name": "link-codex-session-api",
            "repoPath": str(git_repo),
            "profile": "safe-edit",
            "launch": False,
        },
    )
    assert response.status_code == 200, response.text
    session_id = response.json()["id"]

    response = client.post(
        f"/api/sessions/{session_id}/codex-session-link",
        json={
            "codexSessionId": "019ce115-d070-7053-b385-870d5e021ea7",
            "codexRolloutPath": "/tmp/rollout.jsonl",
            "codexUpdatedAt": 2,
        },
    )

    assert response.status_code == 200
    assert response.json()["codex_session_id"] == "019ce115-d070-7053-b385-870d5e021ea7"
    assert response.json()["codex_rollout_path"] == "/tmp/rollout.jsonl"
    assert response.json()["codex_updated_at"] == 2


def test_api_lists_validation_history(configured_modules, git_repo):
    from app.api import server
    from app.services.sessions import record_validation_history

    importlib.reload(server)
    client = TestClient(server.app)

    response = client.post(
        "/api/sessions/start",
        json={
            "name": "validation-history-api",
            "repoPath": str(git_repo),
            "profile": "safe-edit",
            "launch": False,
        },
    )
    assert response.status_code == 200, response.text
    session_id = response.json()["id"]

    record_validation_history(
        session_id,
        kind="tests",
        timestamp="2026-04-03T10:00:00+00:00",
        activity="none",
        status="passed",
        source="status_change",
        details={"previous_status": "unknown"},
    )
    record_validation_history(
        session_id,
        kind="build",
        timestamp="2026-04-03T10:01:00+00:00",
        activity="active",
        status="unknown",
        source="activity_change",
        details={"previous_activity": "none"},
    )

    response = client.get(f"/api/sessions/{session_id}/validation-history?limit=10")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 2
    assert payload[0]["kind"] == "build"
    assert payload[0]["activity"] == "active"
    assert payload[1]["kind"] == "tests"
    assert payload[1]["status"] == "passed"

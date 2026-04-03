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
    assert rows[0]["health_label"] == "healthy"
    assert rows[0]["priority_score"] == 46
    assert rows[0]["repo_risk_label"] == "low"
    assert rows[0]["review_readiness_state"] == "unknown"
    assert rows[0]["completion_state"] == "unknown"
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

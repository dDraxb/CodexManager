from __future__ import annotations

import importlib

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

    response = client.get("/api/sessions")
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1

    sid = rows[0]["id"]
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
    assert "repo path is not accessible" in response.text


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
        json={"codexSessionId": "019ce115-d070-7053-b385-870d5e021ea7"},
    )

    assert response.status_code == 200
    assert response.json()["codex_session_id"] == "019ce115-d070-7053-b385-870d5e021ea7"

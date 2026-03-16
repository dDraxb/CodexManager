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

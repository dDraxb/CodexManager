from __future__ import annotations

import json

import pytest


def test_read_manager_rules_summarizes_valid_document(tmp_path, monkeypatch):
    from app.services.manager_rules import read_manager_rules

    codexmgr_home = tmp_path / ".codexmgr"
    codexmgr_home.mkdir()
    monkeypatch.setenv("CODEXMGR_HOME", str(codexmgr_home))
    (codexmgr_home / "manager-rules.json").write_text(
        json.dumps(
            {
                "version": 1,
                "rules": [
                    {
                        "id": "repo-autonomy-defaults",
                        "label": "Repo autonomy defaults",
                        "category": "autonomy",
                        "enabled": True,
                        "scope": {"level": "workspace", "repo_path": "/repo/service-a"},
                        "notes": "Baseline limit for writable sessions.",
                        "content": {
                            "max_agents": 2,
                            "allow_background_tasks": True,
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    payload = read_manager_rules()

    assert payload["exists"] is True
    assert payload["valid"] is True
    assert payload["ruleCount"] == 1
    assert payload["rules"] == [
        {
            "id": "repo-autonomy-defaults",
            "label": "Repo autonomy defaults",
            "category": "autonomy",
            "enabled": True,
            "scope": {"level": "workspace", "repo_path": "/repo/service-a", "preset_id": ""},
            "scopeSummary": "workspace · /repo/service-a",
            "notes": "Baseline limit for writable sessions.",
            "contentKeys": ["allow_background_tasks", "max_agents"],
            "content": {
                "max_agents": 2,
                "allow_background_tasks": True,
            },
        }
    ]


def test_write_manager_rules_rejects_invalid_rule_shape(tmp_path, monkeypatch):
    from app.services.manager_rules import ManagerRulesError, write_manager_rules

    codexmgr_home = tmp_path / ".codexmgr"
    codexmgr_home.mkdir()
    monkeypatch.setenv("CODEXMGR_HOME", str(codexmgr_home))

    with pytest.raises(ManagerRulesError, match="invalid 'content'; expected object"):
        write_manager_rules(
            content=json.dumps(
                {
                    "version": 1,
                    "rules": [
                        {
                            "id": "bad-rule",
                            "content": ["should", "be", "an", "object"],
                        }
                    ],
                }
            )
        )


def test_effective_session_defaults_merge_global_and_workspace_rules(tmp_path, monkeypatch):
    from app.services.manager_rules import effective_session_defaults

    codexmgr_home = tmp_path / ".codexmgr"
    codexmgr_home.mkdir()
    monkeypatch.setenv("CODEXMGR_HOME", str(codexmgr_home))
    (codexmgr_home / "manager-rules.json").write_text(
        json.dumps(
            {
                "version": 1,
                "rules": [
                    {
                        "id": "global-session-defaults",
                        "category": "session_defaults",
                        "scope": {"level": "global"},
                        "content": {
                            "profile": "safe-edit",
                            "approval_policy": "on-request",
                            "launch": True,
                        },
                    },
                    {
                        "id": "repo-session-defaults",
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

    payload = effective_session_defaults(repo_path="/repo/service-a/api")

    assert payload["defaults"] == {
        "profile": "full-agent",
        "approvalPolicy": "on-request",
        "launch": True,
        "createWorktreeForWrites": True,
        "requireChangelog": True,
    }
    assert [rule["id"] for rule in payload["appliedRules"]] == [
        "global-session-defaults",
        "repo-session-defaults",
    ]


def test_preview_manager_rule_matches_returns_rules_and_defaults(tmp_path, monkeypatch):
    from app.services.manager_rules import preview_manager_rule_matches

    codexmgr_home = tmp_path / ".codexmgr"
    codexmgr_home.mkdir()
    monkeypatch.setenv("CODEXMGR_HOME", str(codexmgr_home))
    (codexmgr_home / "manager-rules.json").write_text(
        json.dumps(
            {
                "version": 1,
                "rules": [
                    {
                        "id": "global-session-defaults",
                        "label": "Global session defaults",
                        "category": "session_defaults",
                        "scope": {"level": "global"},
                        "content": {
                            "profile": "safe-edit",
                            "launch": True,
                        },
                    },
                    {
                        "id": "repo-autonomy",
                        "label": "Repo autonomy caps",
                        "category": "autonomy",
                        "scope": {"level": "workspace", "repo_path": "/repo/service-a"},
                        "content": {
                            "max_agents": 2,
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    payload = preview_manager_rule_matches(repo_path="/repo/service-a/api")

    assert payload["repoPath"] == "/repo/service-a/api"
    assert payload["presetId"] == ""
    assert [rule["id"] for rule in payload["matchedRules"]] == [
        "global-session-defaults",
        "repo-autonomy",
    ]
    assert payload["effectiveSessionDefaults"]["defaults"] == {
        "profile": "safe-edit",
        "launch": True,
    }

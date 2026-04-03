from __future__ import annotations

import json


def test_list_repo_policies_returns_normalized_rules(tmp_path, monkeypatch):
    from app.services.repo_policy_rules import list_repo_policies

    codexmgr_home = tmp_path / ".codexmgr"
    codexmgr_home.mkdir()
    monkeypatch.setenv("CODEXMGR_HOME", str(codexmgr_home))
    (codexmgr_home / "repo-policies.json").write_text(
        json.dumps(
            {
                "policies": {
                    "php-main-guard": {
                        "label": "PHP Main Guard",
                        "match": {"path_prefixes": ["/Users/davidblom/Projects/Topicus/Llamaserve"]},
                        "defaults": {"require_changelog": True, "profile": "safe-edit"},
                        "rules": {"protected_branches": ["main"], "require_worktree_for_write": True},
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    rows = list_repo_policies()

    assert rows == [
        {
            "policy_id": "php-main-guard",
            "label": "PHP Main Guard",
            "path_prefixes": ["/Users/davidblom/Projects/Topicus/Llamaserve"],
            "protected_branches": ["main"],
            "require_worktree_for_write": True,
            "require_changelog": True,
            "default_profile": "safe-edit",
            "default_approval_policy": None,
        }
    ]


def test_match_repo_policy_prefers_longest_matching_prefix(tmp_path, monkeypatch):
    from app.services.repo_policy_rules import match_repo_policy

    codexmgr_home = tmp_path / ".codexmgr"
    codexmgr_home.mkdir()
    monkeypatch.setenv("CODEXMGR_HOME", str(codexmgr_home))
    (codexmgr_home / "repo-policies.json").write_text(
        json.dumps(
            {
                "policies": {
                    "broad": {
                        "match": {"path_prefixes": ["/repo"]},
                        "rules": {"protected_branches": ["main"]},
                    },
                    "specific": {
                        "match": {"path_prefixes": ["/repo/service-a"]},
                        "rules": {"protected_branches": ["develop"], "require_worktree_for_write": True},
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    rule = match_repo_policy("/repo/service-a/api")

    assert rule is not None
    assert rule.policy_id == "specific"
    assert rule.protected_branches == ["develop"]
    assert rule.require_worktree_for_write is True

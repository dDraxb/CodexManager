from __future__ import annotations


def test_database_connections_enable_busy_timeout_and_wal(configured_modules, tmp_path):
    from app.db.database import _connect

    db_path = tmp_path / "codexmgr.db"
    conn = _connect(db_path)
    try:
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        synchronous = conn.execute("PRAGMA synchronous").fetchone()[0]
    finally:
        conn.close()

    assert str(journal_mode).lower() == "wal"
    assert busy_timeout == 30000
    assert synchronous == 1


def test_database_migrates_existing_sessions_to_codex_provider(configured_modules, git_repo):
    from app.services.sessions import create_managed_session, get_session

    session = create_managed_session(
        name="old-provider-migration",
        repo_path=str(git_repo),
        profile="safe-edit",
        prompt="Check provider migration",
        approval_policy="on-request",
        create_worktree_for_writes=False,
        auto_init_git=False,
        launch=False,
    )

    database = configured_modules["database"]
    with database.get_conn() as conn:
        conn.execute(
            """
            UPDATE sessions
            SET codex_session_id = ?, codex_rollout_path = ?, codex_updated_at = ?
            WHERE id = ?
            """,
            ("cdx_old", "/tmp/old-rollout.jsonl", 123, session.id),
        )
        conn.execute("ALTER TABLE sessions DROP COLUMN external_session_id")
        conn.execute("ALTER TABLE sessions DROP COLUMN external_transcript_path")
        conn.execute("ALTER TABLE sessions DROP COLUMN external_updated_at")
        conn.execute("ALTER TABLE sessions DROP COLUMN provider")

    database.init_db(force=True)

    migrated = get_session(session.id)
    assert migrated is not None
    assert migrated.provider == "codex"
    assert migrated.external_session_id == "cdx_old"
    assert migrated.external_transcript_path == "/tmp/old-rollout.jsonl"
    assert migrated.external_updated_at == 123

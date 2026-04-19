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

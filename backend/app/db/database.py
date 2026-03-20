from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app.core.constants import APP_HOME, DB_PATH, SESSIONS_DIR, WORKTREES_DIR


def ensure_storage() -> None:
    APP_HOME.mkdir(parents=True, exist_ok=True)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    WORKTREES_DIR.mkdir(parents=True, exist_ok=True)


def _connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_conn() -> sqlite3.Connection:
    ensure_storage()
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL UNIQUE,
              mode TEXT NOT NULL CHECK(mode in ('managed','adopted')),
              status TEXT NOT NULL CHECK(status in (
                'created','starting','running','waiting_input','idle','finished','failed','stopped','lost'
              )),
              codex_session_id TEXT,
              codex_rollout_path TEXT,
              codex_updated_at INTEGER,
              repo_path TEXT NOT NULL,
              worktree_path TEXT,
              branch TEXT,
              profile TEXT NOT NULL,
              approval_policy TEXT,
              allow_write INTEGER NOT NULL DEFAULT 0,
              allow_shell INTEGER NOT NULL DEFAULT 0,
              tmux_session TEXT,
              pid INTEGER,
              prompt TEXT,
              created_at TEXT NOT NULL,
              started_at TEXT,
              finished_at TEXT,
              last_activity_at TEXT,
              last_known_activity TEXT,
              changed_files_count INTEGER NOT NULL DEFAULT 0,
              changed_files_preview TEXT NOT NULL DEFAULT '[]',
              test_status TEXT,
              lint_status TEXT,
              exit_code INTEGER,
              log_path TEXT NOT NULL,
              cwd TEXT,
              target_label TEXT,
              observability TEXT NOT NULL DEFAULT 'full' CHECK(observability in ('full','reduced')),
              needs_attention INTEGER NOT NULL DEFAULT 0,
              require_changelog INTEGER NOT NULL DEFAULT 0,
              attachment_state TEXT CHECK(attachment_state in ('attached','detached')),
              last_attached_at TEXT,
              last_detached_at TEXT,
              output_fingerprint TEXT,
              output_observed_at TEXT,
              updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              session_id TEXT NOT NULL,
              timestamp TEXT NOT NULL,
              type TEXT NOT NULL,
              message TEXT NOT NULL,
              metadata_json TEXT,
              FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_session_time ON events(session_id, timestamp)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status)"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_tmux_session ON sessions(tmux_session) WHERE tmux_session IS NOT NULL"
        )
        _ensure_session_columns(conn)


def _ensure_session_columns(conn: sqlite3.Connection) -> None:
    existing = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(sessions)").fetchall()
    }
    alter_statements = [
        ("lint_status", "ALTER TABLE sessions ADD COLUMN lint_status TEXT"),
        ("observability", "ALTER TABLE sessions ADD COLUMN observability TEXT NOT NULL DEFAULT 'full'"),
        ("needs_attention", "ALTER TABLE sessions ADD COLUMN needs_attention INTEGER NOT NULL DEFAULT 0"),
        ("require_changelog", "ALTER TABLE sessions ADD COLUMN require_changelog INTEGER NOT NULL DEFAULT 0"),
        ("codex_rollout_path", "ALTER TABLE sessions ADD COLUMN codex_rollout_path TEXT"),
        ("codex_updated_at", "ALTER TABLE sessions ADD COLUMN codex_updated_at INTEGER"),
        ("attachment_state", "ALTER TABLE sessions ADD COLUMN attachment_state TEXT"),
        ("last_attached_at", "ALTER TABLE sessions ADD COLUMN last_attached_at TEXT"),
        ("last_detached_at", "ALTER TABLE sessions ADD COLUMN last_detached_at TEXT"),
        ("output_fingerprint", "ALTER TABLE sessions ADD COLUMN output_fingerprint TEXT"),
        ("output_observed_at", "ALTER TABLE sessions ADD COLUMN output_observed_at TEXT"),
        ("updated_at", "ALTER TABLE sessions ADD COLUMN updated_at TEXT"),
    ]
    for column, statement in alter_statements:
        if column not in existing:
            conn.execute(statement)
    conn.execute(
        "UPDATE sessions SET updated_at = COALESCE(updated_at, created_at), observability = COALESCE(observability, 'full')"
    )

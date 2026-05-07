from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from app.core.constants import APP_HOME, DB_PATH, SESSIONS_DIR, WORKTREES_DIR


_init_lock = threading.Lock()
_initialized_db_path: Path | None = None


def ensure_storage() -> None:
    APP_HOME.mkdir(parents=True, exist_ok=True)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    WORKTREES_DIR.mkdir(parents=True, exist_ok=True)


def _connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
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


def init_db(force: bool = False) -> None:
    global _initialized_db_path
    if not force and _initialized_db_path == DB_PATH and DB_PATH.exists():
        return

    with _init_lock:
        if not force and _initialized_db_path == DB_PATH and DB_PATH.exists():
            return

        with get_conn() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
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
              parent_session_id TEXT,
              automation_action TEXT,
              created_at TEXT NOT NULL,
              started_at TEXT,
              finished_at TEXT,
              last_activity_at TEXT,
              last_known_activity TEXT,
              changed_files_count INTEGER NOT NULL DEFAULT 0,
              changed_files_preview TEXT NOT NULL DEFAULT '[]',
              initial_changed_files_count INTEGER NOT NULL DEFAULT 0,
              initial_changed_files_preview TEXT NOT NULL DEFAULT '[]',
              dirty_start_state TEXT NOT NULL DEFAULT 'clean',
              dirty_start_reason TEXT,
              changed_since_start INTEGER NOT NULL DEFAULT 0,
              changed_since_start_reason TEXT,
              work_phase TEXT NOT NULL DEFAULT 'unknown',
              work_phase_confidence TEXT NOT NULL DEFAULT 'low',
              work_phase_reason TEXT,
              last_major_phase TEXT NOT NULL DEFAULT 'unknown',
              last_major_phase_confidence TEXT NOT NULL DEFAULT 'low',
              last_major_phase_reason TEXT,
              block_category TEXT,
              block_reason TEXT,
              health_score INTEGER NOT NULL DEFAULT 0,
              health_label TEXT NOT NULL DEFAULT 'monitor',
              health_reason TEXT NOT NULL DEFAULT '',
              health_evidence TEXT,
              priority_score INTEGER NOT NULL DEFAULT 0,
              priority_reason TEXT NOT NULL DEFAULT '',
              priority_evidence TEXT,
              repo_risk_label TEXT NOT NULL DEFAULT 'low',
              repo_risk_reason TEXT NOT NULL DEFAULT '',
              repo_overlap_count INTEGER NOT NULL DEFAULT 0,
              repo_overlap_preview TEXT NOT NULL DEFAULT '[]',
              repo_policy_id TEXT,
              repo_policy_label TEXT,
              repo_policy_json TEXT,
              protected_branch_state TEXT NOT NULL DEFAULT 'clear',
              protected_branch_reason TEXT,
              isolation_state TEXT NOT NULL DEFAULT 'not_required',
              isolation_reason TEXT,
              validation_recipe_id TEXT,
              validation_recipe_json TEXT NOT NULL DEFAULT '[]',
              missing_validation_checks_json TEXT NOT NULL DEFAULT '[]',
              optional_validation_checks_json TEXT NOT NULL DEFAULT '[]',
              validation_policy_state TEXT NOT NULL DEFAULT 'unknown',
              validation_policy_reason TEXT,
              review_readiness_state TEXT NOT NULL DEFAULT 'unknown',
              review_readiness_reason TEXT,
              completion_state TEXT NOT NULL DEFAULT 'unknown',
              completion_reason TEXT,
              validation_coverage_reason TEXT,
              last_green_validation_kind TEXT,
              last_green_validation_at TEXT,
              last_green_changed_files_count INTEGER NOT NULL DEFAULT 0,
              last_green_changed_files_preview TEXT NOT NULL DEFAULT '[]',
              changed_since_green_validation INTEGER NOT NULL DEFAULT 0,
              changed_since_green_reason TEXT,
              test_activity TEXT NOT NULL DEFAULT 'none',
              test_status TEXT,
              test_status_at TEXT,
              lint_activity TEXT NOT NULL DEFAULT 'none',
              lint_status TEXT,
              lint_status_at TEXT,
              build_activity TEXT NOT NULL DEFAULT 'none',
              build_status TEXT,
              build_status_at TEXT,
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
            """
            CREATE TABLE IF NOT EXISTS validation_history (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              session_id TEXT NOT NULL,
              timestamp TEXT NOT NULL,
              kind TEXT NOT NULL CHECK(kind in ('tests','lint','build')),
              activity TEXT,
              status TEXT,
              source TEXT NOT NULL DEFAULT 'reconcile',
              details_json TEXT,
              FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
            )
            """
        )
            conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_validation_history_session_time ON validation_history(session_id, timestamp)"
        )
            conn.execute(
            """
            CREATE TABLE IF NOT EXISTS session_handoffs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              session_id TEXT NOT NULL,
              timestamp TEXT NOT NULL,
              kind TEXT NOT NULL DEFAULT 'generated' CHECK(kind in ('generated','manual','stop','archive','resume')),
              goal_summary TEXT NOT NULL DEFAULT '',
              current_state_summary TEXT NOT NULL DEFAULT '',
              unresolved_questions TEXT NOT NULL DEFAULT '',
              validation_state TEXT NOT NULL DEFAULT '',
              files_touched TEXT NOT NULL DEFAULT '',
              suggested_next_actions TEXT NOT NULL DEFAULT '',
              final_disposition TEXT NOT NULL DEFAULT '',
              human_notes TEXT NOT NULL DEFAULT '',
              resume_brief TEXT NOT NULL DEFAULT '',
              automation_recommendations_json TEXT NOT NULL DEFAULT '[]',
              FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
            )
            """
        )
            conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_session_handoffs_session_time ON session_handoffs(session_id, timestamp)"
        )
            conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status)"
        )
            conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_tmux_session ON sessions(tmux_session) WHERE tmux_session IS NOT NULL"
        )
            _ensure_session_columns(conn)
            _ensure_handoff_table(conn)
        _initialized_db_path = DB_PATH


def _ensure_handoff_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS session_handoffs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          session_id TEXT NOT NULL,
          timestamp TEXT NOT NULL,
          kind TEXT NOT NULL DEFAULT 'generated' CHECK(kind in ('generated','manual','stop','archive','resume')),
          goal_summary TEXT NOT NULL DEFAULT '',
          current_state_summary TEXT NOT NULL DEFAULT '',
          unresolved_questions TEXT NOT NULL DEFAULT '',
          validation_state TEXT NOT NULL DEFAULT '',
          files_touched TEXT NOT NULL DEFAULT '',
          suggested_next_actions TEXT NOT NULL DEFAULT '',
          final_disposition TEXT NOT NULL DEFAULT '',
          human_notes TEXT NOT NULL DEFAULT '',
          resume_brief TEXT NOT NULL DEFAULT '',
          automation_recommendations_json TEXT NOT NULL DEFAULT '[]',
          FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_session_handoffs_session_time ON session_handoffs(session_id, timestamp)"
    )


def _ensure_session_columns(conn: sqlite3.Connection) -> None:
    existing = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(sessions)").fetchall()
    }
    alter_statements = [
        ("lint_status", "ALTER TABLE sessions ADD COLUMN lint_status TEXT"),
        ("work_phase", "ALTER TABLE sessions ADD COLUMN work_phase TEXT NOT NULL DEFAULT 'unknown'"),
        ("initial_changed_files_count", "ALTER TABLE sessions ADD COLUMN initial_changed_files_count INTEGER NOT NULL DEFAULT 0"),
        ("initial_changed_files_preview", "ALTER TABLE sessions ADD COLUMN initial_changed_files_preview TEXT NOT NULL DEFAULT '[]'"),
        ("dirty_start_state", "ALTER TABLE sessions ADD COLUMN dirty_start_state TEXT NOT NULL DEFAULT 'clean'"),
        ("dirty_start_reason", "ALTER TABLE sessions ADD COLUMN dirty_start_reason TEXT"),
        ("changed_since_start", "ALTER TABLE sessions ADD COLUMN changed_since_start INTEGER NOT NULL DEFAULT 0"),
        ("changed_since_start_reason", "ALTER TABLE sessions ADD COLUMN changed_since_start_reason TEXT"),
        ("work_phase_confidence", "ALTER TABLE sessions ADD COLUMN work_phase_confidence TEXT NOT NULL DEFAULT 'low'"),
        ("work_phase_reason", "ALTER TABLE sessions ADD COLUMN work_phase_reason TEXT"),
        ("last_major_phase", "ALTER TABLE sessions ADD COLUMN last_major_phase TEXT NOT NULL DEFAULT 'unknown'"),
        ("last_major_phase_confidence", "ALTER TABLE sessions ADD COLUMN last_major_phase_confidence TEXT NOT NULL DEFAULT 'low'"),
        ("last_major_phase_reason", "ALTER TABLE sessions ADD COLUMN last_major_phase_reason TEXT"),
        ("block_category", "ALTER TABLE sessions ADD COLUMN block_category TEXT"),
        ("block_reason", "ALTER TABLE sessions ADD COLUMN block_reason TEXT"),
        ("health_score", "ALTER TABLE sessions ADD COLUMN health_score INTEGER NOT NULL DEFAULT 0"),
        ("health_label", "ALTER TABLE sessions ADD COLUMN health_label TEXT NOT NULL DEFAULT 'monitor'"),
        ("health_reason", "ALTER TABLE sessions ADD COLUMN health_reason TEXT NOT NULL DEFAULT ''"),
        ("health_evidence", "ALTER TABLE sessions ADD COLUMN health_evidence TEXT"),
        ("priority_score", "ALTER TABLE sessions ADD COLUMN priority_score INTEGER NOT NULL DEFAULT 0"),
        ("priority_reason", "ALTER TABLE sessions ADD COLUMN priority_reason TEXT NOT NULL DEFAULT ''"),
        ("priority_evidence", "ALTER TABLE sessions ADD COLUMN priority_evidence TEXT"),
        ("repo_risk_label", "ALTER TABLE sessions ADD COLUMN repo_risk_label TEXT NOT NULL DEFAULT 'low'"),
        ("repo_risk_reason", "ALTER TABLE sessions ADD COLUMN repo_risk_reason TEXT NOT NULL DEFAULT ''"),
        ("repo_overlap_count", "ALTER TABLE sessions ADD COLUMN repo_overlap_count INTEGER NOT NULL DEFAULT 0"),
        ("repo_overlap_preview", "ALTER TABLE sessions ADD COLUMN repo_overlap_preview TEXT NOT NULL DEFAULT '[]'"),
        ("repo_policy_id", "ALTER TABLE sessions ADD COLUMN repo_policy_id TEXT"),
        ("repo_policy_label", "ALTER TABLE sessions ADD COLUMN repo_policy_label TEXT"),
        ("repo_policy_json", "ALTER TABLE sessions ADD COLUMN repo_policy_json TEXT"),
        ("protected_branch_state", "ALTER TABLE sessions ADD COLUMN protected_branch_state TEXT NOT NULL DEFAULT 'clear'"),
        ("protected_branch_reason", "ALTER TABLE sessions ADD COLUMN protected_branch_reason TEXT"),
        ("isolation_state", "ALTER TABLE sessions ADD COLUMN isolation_state TEXT NOT NULL DEFAULT 'not_required'"),
        ("isolation_reason", "ALTER TABLE sessions ADD COLUMN isolation_reason TEXT"),
        ("validation_recipe_id", "ALTER TABLE sessions ADD COLUMN validation_recipe_id TEXT"),
        ("validation_recipe_json", "ALTER TABLE sessions ADD COLUMN validation_recipe_json TEXT NOT NULL DEFAULT '[]'"),
        ("missing_validation_checks_json", "ALTER TABLE sessions ADD COLUMN missing_validation_checks_json TEXT NOT NULL DEFAULT '[]'"),
        ("optional_validation_checks_json", "ALTER TABLE sessions ADD COLUMN optional_validation_checks_json TEXT NOT NULL DEFAULT '[]'"),
        ("validation_policy_state", "ALTER TABLE sessions ADD COLUMN validation_policy_state TEXT NOT NULL DEFAULT 'unknown'"),
        ("validation_policy_reason", "ALTER TABLE sessions ADD COLUMN validation_policy_reason TEXT"),
        ("review_readiness_state", "ALTER TABLE sessions ADD COLUMN review_readiness_state TEXT NOT NULL DEFAULT 'unknown'"),
        ("review_readiness_reason", "ALTER TABLE sessions ADD COLUMN review_readiness_reason TEXT"),
        ("completion_state", "ALTER TABLE sessions ADD COLUMN completion_state TEXT NOT NULL DEFAULT 'unknown'"),
        ("completion_reason", "ALTER TABLE sessions ADD COLUMN completion_reason TEXT"),
        ("validation_coverage_reason", "ALTER TABLE sessions ADD COLUMN validation_coverage_reason TEXT"),
        ("last_green_validation_kind", "ALTER TABLE sessions ADD COLUMN last_green_validation_kind TEXT"),
        ("last_green_validation_at", "ALTER TABLE sessions ADD COLUMN last_green_validation_at TEXT"),
        ("last_green_changed_files_count", "ALTER TABLE sessions ADD COLUMN last_green_changed_files_count INTEGER NOT NULL DEFAULT 0"),
        ("last_green_changed_files_preview", "ALTER TABLE sessions ADD COLUMN last_green_changed_files_preview TEXT NOT NULL DEFAULT '[]'"),
        ("changed_since_green_validation", "ALTER TABLE sessions ADD COLUMN changed_since_green_validation INTEGER NOT NULL DEFAULT 0"),
        ("changed_since_green_reason", "ALTER TABLE sessions ADD COLUMN changed_since_green_reason TEXT"),
        ("test_activity", "ALTER TABLE sessions ADD COLUMN test_activity TEXT NOT NULL DEFAULT 'none'"),
        ("test_status_at", "ALTER TABLE sessions ADD COLUMN test_status_at TEXT"),
        ("observability", "ALTER TABLE sessions ADD COLUMN observability TEXT NOT NULL DEFAULT 'full'"),
        ("lint_activity", "ALTER TABLE sessions ADD COLUMN lint_activity TEXT NOT NULL DEFAULT 'none'"),
        ("lint_status_at", "ALTER TABLE sessions ADD COLUMN lint_status_at TEXT"),
        ("build_activity", "ALTER TABLE sessions ADD COLUMN build_activity TEXT NOT NULL DEFAULT 'none'"),
        ("build_status", "ALTER TABLE sessions ADD COLUMN build_status TEXT"),
        ("build_status_at", "ALTER TABLE sessions ADD COLUMN build_status_at TEXT"),
        ("needs_attention", "ALTER TABLE sessions ADD COLUMN needs_attention INTEGER NOT NULL DEFAULT 0"),
        ("require_changelog", "ALTER TABLE sessions ADD COLUMN require_changelog INTEGER NOT NULL DEFAULT 0"),
        ("codex_rollout_path", "ALTER TABLE sessions ADD COLUMN codex_rollout_path TEXT"),
        ("codex_updated_at", "ALTER TABLE sessions ADD COLUMN codex_updated_at INTEGER"),
        ("attachment_state", "ALTER TABLE sessions ADD COLUMN attachment_state TEXT"),
        ("last_attached_at", "ALTER TABLE sessions ADD COLUMN last_attached_at TEXT"),
        ("last_detached_at", "ALTER TABLE sessions ADD COLUMN last_detached_at TEXT"),
        ("output_fingerprint", "ALTER TABLE sessions ADD COLUMN output_fingerprint TEXT"),
        ("output_observed_at", "ALTER TABLE sessions ADD COLUMN output_observed_at TEXT"),
        ("parent_session_id", "ALTER TABLE sessions ADD COLUMN parent_session_id TEXT"),
        ("automation_action", "ALTER TABLE sessions ADD COLUMN automation_action TEXT"),
        ("updated_at", "ALTER TABLE sessions ADD COLUMN updated_at TEXT"),
    ]
    for column, statement in alter_statements:
        if column not in existing:
            try:
                conn.execute(statement)
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():
                    raise
    conn.execute(
        "UPDATE sessions SET updated_at = COALESCE(updated_at, created_at), observability = COALESCE(observability, 'full'), initial_changed_files_count = COALESCE(initial_changed_files_count, changed_files_count, 0), initial_changed_files_preview = COALESCE(initial_changed_files_preview, changed_files_preview, '[]'), dirty_start_state = CASE WHEN COALESCE(initial_changed_files_count, changed_files_count, 0) > 0 THEN COALESCE(dirty_start_state, 'dirty') ELSE COALESCE(dirty_start_state, 'clean') END, work_phase = COALESCE(work_phase, 'unknown'), work_phase_confidence = COALESCE(work_phase_confidence, 'low'), last_major_phase = COALESCE(last_major_phase, work_phase, 'unknown'), last_major_phase_confidence = COALESCE(last_major_phase_confidence, work_phase_confidence, 'low'), health_score = COALESCE(health_score, 0), health_label = CASE WHEN health_label = 'watch' THEN 'monitor' ELSE COALESCE(health_label, 'monitor') END, health_reason = COALESCE(health_reason, ''), priority_score = COALESCE(priority_score, 0), priority_reason = COALESCE(priority_reason, ''), repo_risk_label = COALESCE(repo_risk_label, 'low'), repo_risk_reason = COALESCE(repo_risk_reason, ''), repo_overlap_count = COALESCE(repo_overlap_count, 0), repo_overlap_preview = COALESCE(repo_overlap_preview, '[]'), protected_branch_state = COALESCE(protected_branch_state, 'clear'), isolation_state = COALESCE(isolation_state, 'not_required'), validation_recipe_json = COALESCE(validation_recipe_json, '[]'), missing_validation_checks_json = COALESCE(missing_validation_checks_json, '[]'), optional_validation_checks_json = COALESCE(optional_validation_checks_json, '[]'), validation_policy_state = COALESCE(validation_policy_state, 'unknown'), review_readiness_state = COALESCE(review_readiness_state, 'unknown'), completion_state = COALESCE(completion_state, 'unknown'), last_green_changed_files_count = COALESCE(last_green_changed_files_count, 0), last_green_changed_files_preview = COALESCE(last_green_changed_files_preview, '[]'), changed_since_green_validation = COALESCE(changed_since_green_validation, 0), changed_since_start = COALESCE(changed_since_start, 0), repo_policy_json = COALESCE(repo_policy_json, NULL), test_activity = COALESCE(test_activity, 'none'), lint_activity = COALESCE(lint_activity, 'none'), build_activity = COALESCE(build_activity, 'none')"
    )

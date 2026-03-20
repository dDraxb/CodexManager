from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


CODEX_HISTORY_LOOKBACK_GRACE_SECONDS = 60


@dataclass(slots=True)
class CodexThreadCandidate:
    id: str
    cwd: str
    created_at: int
    updated_at: int
    first_user_message: str
    title: str
    rollout_path: str


def _codex_home() -> Path:
    raw = os.environ.get("CODEX_HOME")
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".codex"


def _state_db_path() -> Path | None:
    root = _codex_home()
    candidates = sorted(root.glob("state_*.sqlite"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not candidates:
        return None
    return candidates[0]


def _epoch_from_iso(timestamp: str | None) -> int | None:
    if not timestamp:
        return None
    try:
        parsed = datetime.fromisoformat(timestamp)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.timestamp())


def _normalize_text(value: str | None) -> str:
    return " ".join((value or "").split()).strip().lower()


def _normalize_cwd_filter(cwd: str | None) -> str | None:
    if not cwd:
        return None
    expanded = Path(cwd).expanduser()
    try:
        normalized = expanded.resolve(strict=False)
    except OSError:
        normalized = expanded
    return str(normalized)


def _load_candidates(cwd: str, since_epoch: int) -> list[CodexThreadCandidate]:
    state_db = _state_db_path()
    if state_db is None or not state_db.exists():
        return []

    with sqlite3.connect(state_db) as conn:
        rows = conn.execute(
            """
            SELECT id, cwd, created_at, updated_at, COALESCE(first_user_message, ''), COALESCE(title, ''), COALESCE(rollout_path, '')
            FROM threads
            WHERE cwd = ? AND created_at >= ?
            ORDER BY created_at DESC, updated_at DESC
            LIMIT 20
            """,
            (cwd, max(0, since_epoch - CODEX_HISTORY_LOOKBACK_GRACE_SECONDS)),
        ).fetchall()

    return [
        CodexThreadCandidate(
            id=str(row[0]),
            cwd=str(row[1]),
            created_at=int(row[2]),
            updated_at=int(row[3]),
            first_user_message=str(row[4]),
            title=str(row[5]),
            rollout_path=str(row[6]),
        )
        for row in rows
    ]


def _row_to_candidate(row: Any) -> CodexThreadCandidate:
    return CodexThreadCandidate(
        id=str(row[0]),
        rollout_path=str(row[1]),
        created_at=int(row[2]),
        updated_at=int(row[3]),
        cwd=str(row[4]),
        title=str(row[5]),
        first_user_message=str(row[6]),
    )


def _state_db_connection() -> sqlite3.Connection | None:
    state_db = _state_db_path()
    if state_db is None or not state_db.exists():
        return None
    return sqlite3.connect(state_db)


def find_recent_codex_session_id(cwd: str, prompt: str | None, since: str | None) -> str | None:
    since_epoch = _epoch_from_iso(since)
    if since_epoch is None:
        return None

    candidates = _load_candidates(cwd, since_epoch)
    if not candidates:
        return None

    normalized_prompt = _normalize_text(prompt)
    if normalized_prompt:
        prompt_matches = [
            candidate
            for candidate in candidates
            if _normalize_text(candidate.first_user_message) == normalized_prompt
            or _normalize_text(candidate.title) == normalized_prompt
        ]
        if len(prompt_matches) == 1:
            return prompt_matches[0].id
        if len(prompt_matches) > 1:
            prompt_matches.sort(key=lambda candidate: abs(candidate.created_at - since_epoch))
            return prompt_matches[0].id

    if len(candidates) == 1:
        return candidates[0].id

    newest = candidates[0]
    older = candidates[1:]
    if older and all(candidate.created_at < since_epoch for candidate in older) and newest.created_at >= since_epoch:
        return newest.id

    return None


def get_codex_thread(thread_id: str) -> CodexThreadCandidate | None:
    conn = _state_db_connection()
    if conn is None:
        return None
    with conn:
        row = conn.execute(
            """
            SELECT id, COALESCE(rollout_path, ''), created_at, updated_at, cwd, COALESCE(title, ''), COALESCE(first_user_message, '')
            FROM threads
            WHERE id = ?
            LIMIT 1
            """,
            (thread_id,),
        ).fetchone()
    return _row_to_candidate(row) if row else None


def list_codex_threads(*, cwd: str | None = None, query: str | None = None, limit: int = 20) -> list[CodexThreadCandidate]:
    conn = _state_db_connection()
    if conn is None:
        return []

    clauses: list[str] = []
    params: list[Any] = []
    normalized_cwd = _normalize_cwd_filter(cwd)
    if normalized_cwd:
        clauses.append("(cwd = ? OR cwd LIKE ?)")
        params.extend([normalized_cwd, f"{normalized_cwd}/%"])
    normalized_query = (query or "").strip()
    if normalized_query:
        clauses.append("(title LIKE ? OR first_user_message LIKE ? OR id LIKE ?)")
        needle = f"%{normalized_query}%"
        params.extend([needle, needle, needle])

    where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"""
        SELECT id, COALESCE(rollout_path, ''), created_at, updated_at, cwd, COALESCE(title, ''), COALESCE(first_user_message, '')
        FROM threads
        {where_clause}
        ORDER BY updated_at DESC
        LIMIT ?
    """
    params.append(limit)

    with conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_candidate(row) for row in rows]


def list_resume_candidates(*, thread_id: str | None, cwd: str | None, prompt: str | None, limit: int = 12) -> list[CodexThreadCandidate]:
    candidates: list[CodexThreadCandidate] = []
    seen: set[str] = set()

    if thread_id:
        exact = get_codex_thread(thread_id)
        if exact:
            candidates.append(exact)
            seen.add(exact.id)
            seed_query = exact.title or exact.first_user_message or prompt
        else:
            seed_query = prompt
    else:
        seed_query = prompt

    for candidate in list_codex_threads(cwd=cwd, query=seed_query, limit=limit * 2):
        if candidate.id in seen:
            continue
        candidates.append(candidate)
        seen.add(candidate.id)
        if len(candidates) >= limit:
            break

    return candidates[:limit]

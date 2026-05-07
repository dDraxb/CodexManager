from __future__ import annotations

import json
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


@dataclass(slots=True)
class ImportedCodexSession:
    id: str
    cwd: str
    started_at: str
    updated_at: str
    first_user_message: str
    title: str
    rollout_path: str
    event_count: int
    response_count: int
    command_count: int
    last_event_type: str
    cli_version: str
    model_provider: str
    source: str
    originator: str
    manager_session_id: str | None
    manager_session_name: str | None
    manager_status: str | None


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


def _parse_json_line(raw: str) -> dict[str, Any] | None:
    text = raw.strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _session_files() -> list[Path]:
    root = _codex_home() / "sessions"
    if not root.exists() or not root.is_dir():
        return []
    return sorted(root.rglob("rollout-*.jsonl"), key=lambda path: path.stat().st_mtime, reverse=True)


def _manager_session_link_map() -> dict[str, dict[str, str]]:
    from app.services.sessions import list_sessions

    links: dict[str, dict[str, str]] = {}
    for session in list_sessions():
        if not session.codex_session_id:
            continue
        links[session.codex_session_id] = {
            "id": session.id,
            "name": session.name,
            "status": session.status,
        }
    return links


def _scan_rollout_file(path: Path, manager_links: dict[str, dict[str, str]]) -> ImportedCodexSession | None:
    meta: dict[str, Any] | None = None
    first_user_message = ""
    updated_at = ""
    event_count = 0
    response_count = 0
    command_count = 0
    last_event_type = ""

    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            row = _parse_json_line(raw_line)
            if row is None:
                continue
            event_count += 1
            row_type = str(row.get("type") or "")
            last_event_type = row_type or last_event_type
            updated_at = str(row.get("timestamp") or updated_at)

            if row_type == "session_meta" and isinstance(row.get("payload"), dict):
                meta = row["payload"]
                continue

            if row_type == "response_item":
                response_count += 1
                payload = row.get("payload")
                if isinstance(payload, dict) and str(payload.get("type") or "") == "function_call":
                    command_count += 1
                continue

            if row_type == "event_msg":
                payload = row.get("payload")
                if not isinstance(payload, dict):
                    continue
                payload_type = str(payload.get("type") or "")
                if payload_type == "user_message" and not first_user_message:
                    first_user_message = str(payload.get("message") or "").strip()
                elif payload_type == "exec_command_end":
                    command_count += 1

    if not isinstance(meta, dict):
        return None

    session_id = str(meta.get("id") or "").strip()
    started_at = str(meta.get("timestamp") or "").strip()
    cwd = str(meta.get("cwd") or "").strip()
    if not session_id or not started_at:
        return None

    thread = get_codex_thread(session_id)
    title = thread.title if thread and thread.title else ""
    if not first_user_message and thread and thread.first_user_message:
        first_user_message = thread.first_user_message
    if not title:
        title = first_user_message
    linked = manager_links.get(session_id, {})
    return ImportedCodexSession(
        id=session_id,
        cwd=cwd,
        started_at=started_at,
        updated_at=updated_at or started_at,
        first_user_message=first_user_message,
        title=title,
        rollout_path=str(path),
        event_count=event_count,
        response_count=response_count,
        command_count=command_count,
        last_event_type=last_event_type,
        cli_version=str(meta.get("cli_version") or "").strip(),
        model_provider=str(meta.get("model_provider") or "").strip(),
        source=str(meta.get("source") or "").strip(),
        originator=str(meta.get("originator") or "").strip(),
        manager_session_id=linked.get("id"),
        manager_session_name=linked.get("name"),
        manager_status=linked.get("status"),
    )


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


def list_imported_codex_sessions(*, cwd: str | None = None, query: str | None = None, limit: int = 20) -> list[ImportedCodexSession]:
    normalized_cwd = _normalize_cwd_filter(cwd)
    normalized_query = _normalize_text(query)
    manager_links = _manager_session_link_map()
    rows: list[ImportedCodexSession] = []
    for path in _session_files():
        parsed = _scan_rollout_file(path, manager_links)
        if parsed is None:
            continue
        if normalized_cwd and not (
            parsed.cwd == normalized_cwd or parsed.cwd.startswith(normalized_cwd.rstrip("/") + "/")
        ):
            continue
        if normalized_query:
            haystack = " ".join(
                [
                    parsed.id,
                    parsed.cwd,
                    parsed.title,
                    parsed.first_user_message,
                    parsed.manager_session_name or "",
                ]
            ).lower()
            if normalized_query not in haystack:
                continue
        rows.append(parsed)
        if len(rows) >= limit:
            break
    return rows

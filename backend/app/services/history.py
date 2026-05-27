from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import asdict

from app.models.session import SessionRecord
from app.services.handoff import latest_handoff
from app.services.sessions import list_sessions


ARCHIVE_STATUSES = {"finished", "failed", "stopped", "lost"}


def _matches_query(session: SessionRecord, query: str) -> bool:
    if not query:
        return True
    handoff = latest_handoff(session.id)
    handoff_values = []
    if handoff:
        handoff_values = [
            handoff.goal_summary,
            handoff.current_state_summary,
            handoff.unresolved_questions,
            handoff.validation_state,
            handoff.files_touched,
            handoff.suggested_next_actions,
            handoff.final_disposition,
            handoff.human_notes,
            handoff.resume_brief,
        ]
    haystack = " ".join(
        str(value or "")
        for value in [
            session.id,
            session.name,
            session.provider,
            session.repo_path,
            session.cwd,
            session.target_label,
            session.branch,
            session.profile,
            session.status,
            session.prompt,
            session.health_reason,
            session.priority_reason,
            session.repo_risk_reason,
            session.review_readiness_reason,
            session.completion_reason,
            *handoff_values,
        ]
    ).lower()
    return query.lower() in haystack


def _session_history_row(session: SessionRecord) -> dict:
    handoff = latest_handoff(session.id)
    return {
        **asdict(session),
        "archived": session.status in ARCHIVE_STATUSES,
        "latestHandoff": asdict(handoff) if handoff else None,
    }


def search_session_history(
    *,
    query: str | None = None,
    repo_path: str | None = None,
    status: str | None = None,
    profile: str | None = None,
    validation_state: str | None = None,
    archived: bool | None = None,
    limit: int = 50,
) -> dict:
    rows: list[dict] = []
    normalized_query = (query or "").strip()
    normalized_repo = (repo_path or "").strip()
    for session in list_sessions():
        if normalized_repo and not (
            session.repo_path == normalized_repo or session.repo_path.startswith(normalized_repo.rstrip("/") + "/")
        ):
            continue
        if status and session.status != status:
            continue
        if profile and session.profile != profile:
            continue
        if validation_state and session.validation_policy_state != validation_state:
            continue
        if archived is not None and (session.status in ARCHIVE_STATUSES) != archived:
            continue
        if not _matches_query(session, normalized_query):
            continue
        rows.append(_session_history_row(session))
        if len(rows) >= limit:
            break
    return {
        "sessions": rows,
        "count": len(rows),
        "filters": {
            "query": normalized_query,
            "repoPath": normalized_repo,
            "status": status or "",
            "profile": profile or "",
            "validationState": validation_state or "",
            "archived": archived,
            "limit": limit,
        },
    }


def session_analytics() -> dict:
    sessions = list_sessions()
    by_repo: Counter[str] = Counter()
    by_status: Counter[str] = Counter()
    validation_failures: Counter[str] = Counter()
    abandoned_by_repo: Counter[str] = Counter()
    attention_reasons: Counter[str] = Counter()
    durations: list[int] = []

    for session in sessions:
        repo_key = session.target_label or session.repo_path
        by_repo[repo_key] += 1
        by_status[session.status] += 1
        if session.test_status == "failed":
            validation_failures["tests"] += 1
        if session.lint_status == "failed":
            validation_failures["lint"] += 1
        if session.build_status == "failed":
            validation_failures["build"] += 1
        if session.status in {"failed", "lost", "stopped"} and session.completion_state not in {"ready_for_review", "ready_with_gaps"}:
            abandoned_by_repo[repo_key] += 1
        if session.needs_attention:
            attention_reasons[session.priority_reason or session.health_reason or "needs attention"] += 1
        if session.started_at and session.finished_at:
            # ISO timestamps sort lexically but duration needs tolerant parsing in the UI layer less than here.
            try:
                from datetime import datetime

                started = datetime.fromisoformat(session.started_at)
                finished = datetime.fromisoformat(session.finished_at)
                durations.append(max(0, int((finished - started).total_seconds())))
            except ValueError:
                pass

    repo_rows = [
        {
            "repo": repo,
            "sessions": count,
            "abandoned": abandoned_by_repo.get(repo, 0),
        }
        for repo, count in by_repo.most_common(12)
    ]
    avg_duration = int(sum(durations) / len(durations)) if durations else 0
    return {
        "totalSessions": len(sessions),
        "archivedSessions": sum(1 for session in sessions if session.status in ARCHIVE_STATUSES),
        "activeSessions": sum(1 for session in sessions if session.status not in ARCHIVE_STATUSES),
        "needsAttention": sum(1 for session in sessions if session.needs_attention),
        "averageDurationSeconds": avg_duration,
        "byStatus": dict(by_status),
        "byRepo": repo_rows,
        "validationFailures": dict(validation_failures),
        "attentionReasons": [
            {"reason": reason, "count": count}
            for reason, count in attention_reasons.most_common(8)
        ],
        "repeatFailureRepos": [
            {"repo": repo, "abandoned": count}
            for repo, count in abandoned_by_repo.most_common(8)
        ],
    }


def compare_repo_sessions(repo_path: str) -> dict:
    normalized_repo = repo_path.strip()
    matching = [
        session
        for session in list_sessions()
        if normalized_repo and (
            session.repo_path == normalized_repo or session.repo_path.startswith(normalized_repo.rstrip("/") + "/")
        )
    ]
    touched: dict[str, list[str]] = defaultdict(list)
    for session in matching:
        try:
            files = json.loads(session.changed_files_preview or "[]")
        except json.JSONDecodeError:
            files = []
        for file_path in files:
            touched[str(file_path)].append(session.name)
    overlaps = [
        {"path": path, "sessions": names}
        for path, names in touched.items()
        if len(set(names)) > 1
    ]
    return {
        "repoPath": normalized_repo,
        "sessions": [_session_history_row(session) for session in matching],
        "overlaps": overlaps,
    }

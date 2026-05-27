from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime

from app.db.database import get_conn, init_db
from app.models.handoff import HandoffRecord
from app.models.session import SessionRecord
from app.services.sessions import SessionError, get_session, list_events


VALID_HANDOFF_KINDS = {"generated", "manual", "stop", "archive", "resume"}


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if str(item).strip()]


def _phase_label(value: str | None) -> str:
    return str(value or "unknown").replace("_", " ")


def _validation_summary(session: SessionRecord) -> str:
    checks = [
        ("tests", session.test_status or "unknown"),
        ("lint", session.lint_status or "unknown"),
        ("build", session.build_status or "unknown"),
    ]
    result = ", ".join(f"{kind}: {status}" for kind, status in checks)
    policy = session.validation_policy_state or "unknown"
    reason = session.validation_policy_reason or session.validation_coverage_reason or ""
    return f"{result}; policy: {policy}" + (f"; {reason}" if reason else "")


def automation_recommendations_for_session(session: SessionRecord) -> list[dict]:
    recommendations: list[dict] = []

    def add(kind: str, label: str, reason: str, action: str, priority: int = 50) -> None:
        recommendations.append(
            {
                "kind": kind,
                "label": label,
                "reason": reason,
                "action": action,
                "priority": priority,
            }
        )

    if session.status == "waiting_input":
        add("attention", "Respond to blocked session", "session is waiting for input", "attach", 95)
    if session.status in {"failed", "lost"}:
        add("recovery", "Generate recovery session", f"session is {session.status}", "resume_or_relaunch", 90)
    if session.work_phase == "blocked" or session.block_reason:
        add("unblock", "Assign unblock follow-up", session.block_reason or "session phase is blocked", "spawn_investigation", 88)
    if session.changed_since_green_validation:
        add("validation", "Run validation follow-up", session.changed_since_green_reason or "code changed after last green validation", "spawn_validation", 82)
    if session.validation_policy_state in {"required_missing", "optional_pending"}:
        add("validation", "Complete validation policy", session.validation_policy_reason or "validation policy has gaps", "run_validation_recipe", 80)
    if session.review_readiness_state == "ready" or session.completion_state in {"ready_for_review", "ready_with_gaps"}:
        add("review", "Spawn review agent", session.review_readiness_reason or session.completion_reason or "session appears ready for review", "spawn_review", 78)
    if session.repo_overlap_count > 0:
        add("coordination", "Compare overlapping sessions", session.repo_overlap_preview or "changed files overlap with another session", "compare_sessions", 76)
    if session.status == "idle" and session.needs_attention:
        add("attention", "Inspect idle attention item", session.health_reason or "idle session needs attention", "inspect", 72)
    if session.allow_write and session.isolation_state in {"recommended_missing", "required_missing"}:
        add("safety", "Move writable work into isolation", session.isolation_reason or "writable work is not isolated", "spawn_isolated_followup", 70)
    if session.status in {"finished", "failed", "stopped", "lost"}:
        add("handoff", "Archive with handoff summary", "session has reached an archiveable state", "archive_with_summary", 60)

    if not recommendations:
        add("monitor", "Keep monitoring", session.health_reason or "no urgent automation action detected", "monitor", 20)

    return sorted(recommendations, key=lambda row: int(row["priority"]), reverse=True)


def build_handoff_payload(session: SessionRecord, *, kind: str = "generated", human_notes: str = "") -> dict:
    if kind not in VALID_HANDOFF_KINDS:
        raise SessionError(f"invalid handoff kind '{kind}'")

    changed_files = _json_list(session.changed_files_preview)
    missing_validation = _json_list(session.missing_validation_checks_json)
    events = list_events(session.id, limit=8)
    recent_event_labels = [f"{event.type}: {event.message}" for event in reversed(events[-4:])]

    goal_summary = session.prompt or f"{session.name} in {session.target_label or session.repo_path}"
    current_state = (
        f"{session.provider}; {session.status}; phase {_phase_label(session.work_phase)} "
        f"({session.work_phase_confidence or 'low'} confidence); "
        f"health {session.health_label}: {session.health_reason}"
    )
    unresolved: list[str] = []
    if session.block_reason:
        unresolved.append(session.block_reason)
    if missing_validation:
        unresolved.append("missing validation: " + ", ".join(missing_validation))
    if session.repo_overlap_count:
        unresolved.append("overlapping work: " + (session.repo_overlap_preview or "shared changed files"))
    if session.protected_branch_state == "violation":
        unresolved.append(session.protected_branch_reason or "protected branch violation")
    if not unresolved:
        unresolved.append("none recorded")

    recommendations = automation_recommendations_for_session(session)
    suggested_next_actions = [row["label"] for row in recommendations[:5]]
    disposition = session.completion_reason or session.review_readiness_reason or session.last_known_activity or ""
    resume_lines = [
        f"Goal: {goal_summary}",
        f"State: {current_state}",
        f"Validation: {_validation_summary(session)}",
        f"Files: {', '.join(changed_files[:8]) if changed_files else 'no changed files recorded'}",
        f"Open questions: {'; '.join(unresolved)}",
        f"Next actions: {'; '.join(suggested_next_actions)}",
    ]
    if recent_event_labels:
        resume_lines.append("Recent events: " + " | ".join(recent_event_labels))
    if human_notes.strip():
        resume_lines.append("Notes: " + human_notes.strip())

    return {
        "session_id": session.id,
        "kind": kind,
        "goal_summary": goal_summary,
        "current_state_summary": current_state,
        "unresolved_questions": "\n".join(f"- {item}" for item in unresolved),
        "validation_state": _validation_summary(session),
        "files_touched": "\n".join(changed_files),
        "suggested_next_actions": "\n".join(f"- {item}" for item in suggested_next_actions),
        "final_disposition": disposition,
        "human_notes": human_notes.strip(),
        "resume_brief": "\n".join(resume_lines),
        "automation_recommendations_json": json.dumps(recommendations),
    }


def create_handoff(session_id: str, *, kind: str = "generated", human_notes: str = "") -> HandoffRecord:
    init_db()
    session = get_session(session_id)
    if session is None:
        raise SessionError(f"session '{session_id}' not found")
    payload = build_handoff_payload(session, kind=kind, human_notes=human_notes)
    timestamp = _now_iso()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO session_handoffs (
              session_id, timestamp, kind, goal_summary, current_state_summary,
              unresolved_questions, validation_state, files_touched,
              suggested_next_actions, final_disposition, human_notes,
              resume_brief, automation_recommendations_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session.id,
                timestamp,
                payload["kind"],
                payload["goal_summary"],
                payload["current_state_summary"],
                payload["unresolved_questions"],
                payload["validation_state"],
                payload["files_touched"],
                payload["suggested_next_actions"],
                payload["final_disposition"],
                payload["human_notes"],
                payload["resume_brief"],
                payload["automation_recommendations_json"],
            ),
        )
        row = conn.execute("SELECT * FROM session_handoffs WHERE id = last_insert_rowid()").fetchone()
    return HandoffRecord.from_row(row)


def list_handoffs(session_id: str, limit: int = 20) -> list[HandoffRecord]:
    init_db()
    if get_session(session_id) is None:
        raise SessionError(f"session '{session_id}' not found")
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM session_handoffs
            WHERE session_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (session_id, limit),
        ).fetchall()
    return [HandoffRecord.from_row(row) for row in rows]


def latest_handoff(session_id: str) -> HandoffRecord | None:
    rows = list_handoffs(session_id, limit=1)
    return rows[0] if rows else None


def automation_snapshot(session_id: str) -> dict:
    session = get_session(session_id)
    if session is None:
        raise SessionError(f"session '{session_id}' not found")
    handoff = latest_handoff(session.id)
    return {
        "session": session.id,
        "recommendations": automation_recommendations_for_session(session),
        "latestHandoff": asdict(handoff) if handoff else None,
        "resumeBrief": handoff.resume_brief if handoff else build_handoff_payload(session)["resume_brief"],
    }

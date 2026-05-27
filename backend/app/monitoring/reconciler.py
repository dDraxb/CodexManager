from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from app.core.settings import load_settings
from app.db.database import get_conn
from app.models.session import SessionStatus
from app.runner.client import get_runner_client
from app.runner.contracts import RunnerClient, RunnerError
from app.services.sessions import (
    _event,
    list_sessions,
    record_validation_history,
    refresh_git_state,
    update_status,
)
from app.services.health import assess_session_health
from app.services.priority import assess_session_priority
from app.services.repo_baseline import assess_repo_baseline
from app.services.repo_policy import assess_repo_policy
from app.services.repo_policy_rules import parse_repo_policy
from app.services.repo_risk import assess_repo_risk
from app.services.completion_state import assess_completion_state
from app.services.review_readiness import assess_review_readiness
from app.services.validation import STATUS_FAILED, analyze_validation
from app.services.validation_recipe import validation_policy_state
from app.services.work_phase import (
    PHASE_UNKNOWN,
    infer_work_phase,
)

ATTACH_ACTIVITY_GRACE_SECONDS = 15
LIVE_REPO_STATUSES = {
    SessionStatus.CREATED.value,
    SessionStatus.STARTING.value,
    SessionStatus.RUNNING.value,
    SessionStatus.WAITING_INPUT.value,
}



def _file_age_seconds(path: str) -> int | None:
    p = Path(path)
    if not p.exists():
        return None
    if p.stat().st_size == 0:
        return None
    mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=UTC)
    return int((datetime.now(UTC) - mtime).total_seconds())


def _iso_age_seconds(timestamp: str | None) -> int | None:
    if not timestamp:
        return None
    try:
        observed = datetime.fromisoformat(timestamp)
    except ValueError:
        return None
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=UTC)
    return int((datetime.now(UTC) - observed).total_seconds())


def _pane_fingerprint(lines: list[str]) -> str | None:
    if not lines:
        return None
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def _min_age(current_age: int | None, candidate_age: int | None) -> int | None:
    if current_age is None:
        return candidate_age
    if candidate_age is None:
        return current_age
    return min(current_age, candidate_age)


def _record_output_observation(session_id: str, fingerprint: str, observed_at: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE sessions SET output_fingerprint = ?, output_observed_at = ?, updated_at = ? WHERE id = ?",
            (fingerprint, observed_at, observed_at, session_id),
        )


def _record_output_fingerprint(session_id: str, fingerprint: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE sessions SET output_fingerprint = ?, updated_at = ? WHERE id = ?",
            (fingerprint, datetime.now(UTC).replace(microsecond=0).isoformat(), session_id),
        )


def _record_attachment_state(session_id: str, attachment_state: str, timestamp: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE sessions
            SET attachment_state = ?, last_attached_at = CASE WHEN ? = 'attached' THEN ? ELSE last_attached_at END,
                last_detached_at = CASE WHEN ? = 'detached' THEN ? ELSE last_detached_at END,
                updated_at = ?
            WHERE id = ?
            """,
            (attachment_state, attachment_state, timestamp, attachment_state, timestamp, timestamp, session_id),
        )


def _record_validation_state(
    session_id: str,
    *,
    test_activity: str,
    test_status: str,
    test_status_at: str | None,
    lint_activity: str,
    lint_status: str,
    lint_status_at: str | None,
    build_activity: str,
    build_status: str,
    build_status_at: str | None,
    needs_attention: bool,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE sessions
            SET test_activity = ?, test_status = ?, test_status_at = ?, lint_activity = ?, lint_status = ?, lint_status_at = ?, build_activity = ?, build_status = ?, build_status_at = ?, needs_attention = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                test_activity,
                test_status,
                test_status_at,
                lint_activity,
                lint_status,
                lint_status_at,
                build_activity,
                build_status,
                build_status_at,
                1 if needs_attention else 0,
                datetime.now(UTC).replace(microsecond=0).isoformat(),
                session_id,
            ),
        )


def _record_validation_baseline(
    session_id: str,
    *,
    kind: str | None,
    timestamp: str | None,
    changed_files_count: int,
    changed_files_preview: str,
    changed_since: bool,
    changed_reason: str | None,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE sessions
            SET last_green_validation_kind = ?, last_green_validation_at = ?,
                last_green_changed_files_count = ?, last_green_changed_files_preview = ?,
                changed_since_green_validation = ?, changed_since_green_reason = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                kind,
                timestamp,
                changed_files_count,
                changed_files_preview,
                1 if changed_since else 0,
                changed_reason,
                datetime.now(UTC).replace(microsecond=0).isoformat(),
                session_id,
            ),
        )


def _record_validation_coverage(
    session_id: str,
    *,
    missing_checks_json: str,
    optional_checks_json: str,
    policy_state: str,
    policy_reason: str | None,
    coverage_reason: str | None,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE sessions
            SET missing_validation_checks_json = ?, optional_validation_checks_json = ?,
                validation_policy_state = ?, validation_policy_reason = ?,
                validation_coverage_reason = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                missing_checks_json,
                optional_checks_json,
                policy_state,
                policy_reason,
                coverage_reason,
                datetime.now(UTC).replace(microsecond=0).isoformat(),
                session_id,
            ),
        )


def _record_review_readiness(session_id: str, *, state: str, reason: str | None) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE sessions
            SET review_readiness_state = ?, review_readiness_reason = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                state,
                reason,
                datetime.now(UTC).replace(microsecond=0).isoformat(),
                session_id,
            ),
        )


def _record_completion_state(session_id: str, *, state: str, reason: str | None) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE sessions
            SET completion_state = ?, completion_reason = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                state,
                reason,
                datetime.now(UTC).replace(microsecond=0).isoformat(),
                session_id,
            ),
        )


def _record_validation_transition(
    session_id: str,
    *,
    kind: str,
    timestamp: str,
    activity: str | None,
    status: str | None,
    source: str,
    details: dict | None = None,
) -> None:
    record_validation_history(
        session_id,
        kind=kind,
        timestamp=timestamp,
        activity=activity,
        status=status,
        source=source,
        details=details,
    )


MAJOR_PHASES = {"planning", "reading", "editing", "testing", "blocked", "waiting_input", "reviewing", "completed"}


def _record_work_phase(
    session_id: str,
    work_phase: str,
    confidence: str,
    *,
    reason: str | None = None,
    last_major_phase: str | None = None,
    last_major_phase_confidence: str | None = None,
    last_major_phase_reason: str | None = None,
    block_category: str | None = None,
    block_reason: str | None = None,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE sessions
            SET work_phase = ?, work_phase_confidence = ?, work_phase_reason = ?,
                last_major_phase = COALESCE(?, last_major_phase),
                last_major_phase_confidence = COALESCE(?, last_major_phase_confidence),
                last_major_phase_reason = COALESCE(?, last_major_phase_reason),
                block_category = ?,
                block_reason = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                work_phase,
                confidence,
                reason,
                last_major_phase,
                last_major_phase_confidence,
                last_major_phase_reason,
                block_category,
                block_reason,
                datetime.now(UTC).replace(microsecond=0).isoformat(),
                session_id,
            ),
        )


def _record_health(session_id: str, score: int, label: str, reason: str, evidence: str | None) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE sessions SET health_score = ?, health_label = ?, health_reason = ?, health_evidence = ?, updated_at = ? WHERE id = ?",
            (score, label, reason, evidence, datetime.now(UTC).replace(microsecond=0).isoformat(), session_id),
        )


def _record_priority(session_id: str, score: int, reason: str, evidence: str | None) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE sessions SET priority_score = ?, priority_reason = ?, priority_evidence = ?, updated_at = ? WHERE id = ?",
            (score, reason, evidence, datetime.now(UTC).replace(microsecond=0).isoformat(), session_id),
        )


def _record_repo_risk(session_id: str, label: str, reason: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE sessions SET repo_risk_label = ?, repo_risk_reason = ?, updated_at = ? WHERE id = ?",
            (label, reason, datetime.now(UTC).replace(microsecond=0).isoformat(), session_id),
        )


def _record_repo_overlap(session_id: str, overlap_paths: list[str]) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE sessions SET repo_overlap_count = ?, repo_overlap_preview = ?, updated_at = ? WHERE id = ?",
            (
                len(overlap_paths),
                json.dumps(overlap_paths[:10]),
                datetime.now(UTC).replace(microsecond=0).isoformat(),
                session_id,
            ),
        )


def _record_repo_policy(
    session_id: str,
    *,
    protected_branch_state: str,
    protected_branch_reason: str | None,
    isolation_state: str,
    isolation_reason: str | None,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE sessions
            SET protected_branch_state = ?, protected_branch_reason = ?,
                isolation_state = ?, isolation_reason = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                protected_branch_state,
                protected_branch_reason,
                isolation_state,
                isolation_reason,
                datetime.now(UTC).replace(microsecond=0).isoformat(),
                session_id,
            ),
        )


def _record_repo_baseline(
    session_id: str,
    *,
    dirty_start_state: str,
    dirty_start_reason: str | None,
    changed_since_start: int,
    changed_since_start_reason: str | None,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE sessions
            SET dirty_start_state = ?, dirty_start_reason = ?,
                changed_since_start = ?, changed_since_start_reason = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                dirty_start_state,
                dirty_start_reason,
                changed_since_start,
                changed_since_start_reason,
                datetime.now(UTC).replace(microsecond=0).isoformat(),
                session_id,
            ),
        )


def _record_codex_history_target(
    session_id: str,
    codex_session_id: str,
    codex_rollout_path: str | None,
    codex_updated_at: int | None,
) -> None:
    timestamp = datetime.now(UTC).replace(microsecond=0).isoformat()
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE sessions
            SET codex_session_id = ?, codex_rollout_path = ?, codex_updated_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (codex_session_id, codex_rollout_path, codex_updated_at, timestamp, session_id),
        )


def _session_needs_attention(session_status: str, *, test_status: str, lint_status: str, build_status: str) -> bool:
    if session_status in {SessionStatus.FAILED.value, SessionStatus.LOST.value, SessionStatus.WAITING_INPUT.value}:
        return True
    return test_status == STATUS_FAILED or lint_status == STATUS_FAILED or build_status == STATUS_FAILED


def _log_timestamp(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).replace(microsecond=0).isoformat()
    except OSError:
        return None


def _backfill_validation_from_log(session) -> tuple[str, str, str | None, str, str, str | None, str, str, str | None]:
    test_activity = session.test_activity or "none"
    test_status = session.test_status or "unknown"
    test_status_at = session.test_status_at
    lint_activity = session.lint_activity or "none"
    lint_status = session.lint_status or "unknown"
    lint_status_at = session.lint_status_at
    build_activity = session.build_activity or "none"
    build_status = session.build_status or "unknown"
    build_status_at = session.build_status_at
    needs_backfill = (
        (test_status == "unknown" and test_status_at is None)
        or (lint_status == "unknown" and lint_status_at is None)
        or (build_status == "unknown" and build_status_at is None)
    )
    if not needs_backfill:
        return (
            test_activity,
            test_status,
            test_status_at,
            lint_activity,
            lint_status,
            lint_status_at,
            build_activity,
            build_status,
            build_status_at,
        )

    log_path = Path(session.log_path)
    if not log_path.exists():
        return (
            test_activity,
            test_status,
            test_status_at,
            lint_activity,
            lint_status,
            lint_status_at,
            build_activity,
            build_status,
            build_status_at,
        )

    snapshot = analyze_validation(log_path.read_text(encoding="utf-8", errors="replace").splitlines())
    timestamp = _log_timestamp(log_path)
    if test_status == "unknown" and snapshot.test_status != "unknown":
        test_status = snapshot.test_status
        test_status_at = timestamp
    if lint_status == "unknown" and snapshot.lint_status != "unknown":
        lint_status = snapshot.lint_status
        lint_status_at = timestamp
    if build_status == "unknown" and snapshot.build_status != "unknown":
        build_status = snapshot.build_status
        build_status_at = timestamp
    return (
        test_activity,
        test_status,
        test_status_at,
        lint_activity,
        lint_status,
        lint_status_at,
        build_activity,
        build_status,
        build_status_at,
    )


def _refresh_validation_state(session, lines: list[str]) -> None:
    test_status_changed = False
    lint_status_changed = False
    build_status_changed = False
    snapshot = analyze_validation(lines)
    timestamp = datetime.now(UTC).replace(microsecond=0).isoformat()
    (
        effective_test_activity,
        effective_test_status,
        effective_test_status_at,
        effective_lint_activity,
        effective_lint_status,
        effective_lint_status_at,
        effective_build_activity,
        effective_build_status,
        effective_build_status_at,
    ) = _backfill_validation_from_log(session)
    if snapshot.test_activity != "none":
        effective_test_activity = snapshot.test_activity
    if snapshot.test_status != "unknown":
        effective_test_status = snapshot.test_status
        if snapshot.test_status != session.test_status:
            effective_test_status_at = timestamp
    if snapshot.lint_activity != "none":
        effective_lint_activity = snapshot.lint_activity
    if snapshot.lint_status != "unknown":
        effective_lint_status = snapshot.lint_status
        if snapshot.lint_status != session.lint_status:
            effective_lint_status_at = timestamp
    if snapshot.build_activity != "none":
        effective_build_activity = snapshot.build_activity
    if snapshot.build_status != "unknown":
        effective_build_status = snapshot.build_status
        if snapshot.build_status != session.build_status:
            effective_build_status_at = timestamp
    if (
        effective_test_activity == session.test_activity
        and effective_test_status == session.test_status
        and effective_test_status_at == session.test_status_at
        and effective_lint_activity == session.lint_activity
        and effective_lint_status == session.lint_status
        and effective_lint_status_at == session.lint_status_at
        and effective_build_activity == session.build_activity
        and effective_build_status == session.build_status
        and effective_build_status_at == session.build_status_at
    ):
        return

    needs_attention = _session_needs_attention(
        session.status,
        test_status=effective_test_status,
        lint_status=effective_lint_status,
        build_status=effective_build_status,
    )
    _record_validation_state(
        session.id,
        test_activity=effective_test_activity,
        test_status=effective_test_status,
        test_status_at=effective_test_status_at,
        lint_activity=effective_lint_activity,
        lint_status=effective_lint_status,
        lint_status_at=effective_lint_status_at,
        build_activity=effective_build_activity,
        build_status=effective_build_status,
        build_status_at=effective_build_status_at,
        needs_attention=needs_attention,
    )
    if effective_test_activity != session.test_activity:
        _record_validation_transition(
            session.id,
            kind="tests",
            timestamp=timestamp,
            activity=effective_test_activity,
            status=effective_test_status,
            source="activity_change",
            details={"previous_activity": session.test_activity, "status_at": effective_test_status_at},
        )
        _event(
            session.id,
            "validation_activity_changed",
            f"Tests {effective_test_activity}",
            {"kind": "tests", "activity": effective_test_activity},
        )
        session.test_activity = effective_test_activity
    if effective_test_status != session.test_status:
        test_status_changed = True
        _record_validation_transition(
            session.id,
            kind="tests",
            timestamp=effective_test_status_at or timestamp,
            activity=effective_test_activity,
            status=effective_test_status,
            source="status_change",
            details={"previous_status": session.test_status},
        )
        _event(
            session.id,
            "validation_changed",
            f"Tests {effective_test_status}",
            {"kind": "tests", "status": effective_test_status},
        )
        session.test_status = effective_test_status
        session.test_status_at = effective_test_status_at
    if effective_lint_activity != session.lint_activity:
        _record_validation_transition(
            session.id,
            kind="lint",
            timestamp=timestamp,
            activity=effective_lint_activity,
            status=effective_lint_status,
            source="activity_change",
            details={"previous_activity": session.lint_activity, "status_at": effective_lint_status_at},
        )
        _event(
            session.id,
            "validation_activity_changed",
            f"Lint {effective_lint_activity}",
            {"kind": "lint", "activity": effective_lint_activity},
        )
        session.lint_activity = effective_lint_activity
    if effective_lint_status != session.lint_status:
        lint_status_changed = True
        _record_validation_transition(
            session.id,
            kind="lint",
            timestamp=effective_lint_status_at or timestamp,
            activity=effective_lint_activity,
            status=effective_lint_status,
            source="status_change",
            details={"previous_status": session.lint_status},
        )
        _event(
            session.id,
            "validation_changed",
            f"Lint {effective_lint_status}",
            {"kind": "lint", "status": effective_lint_status},
        )
        session.lint_status = effective_lint_status
        session.lint_status_at = effective_lint_status_at
    if effective_build_activity != session.build_activity:
        _record_validation_transition(
            session.id,
            kind="build",
            timestamp=timestamp,
            activity=effective_build_activity,
            status=effective_build_status,
            source="activity_change",
            details={"previous_activity": session.build_activity, "status_at": effective_build_status_at},
        )
        _event(
            session.id,
            "validation_activity_changed",
            f"Build {effective_build_activity}",
            {"kind": "build", "activity": effective_build_activity},
        )
        session.build_activity = effective_build_activity
    if effective_build_status != session.build_status:
        build_status_changed = True
        _record_validation_transition(
            session.id,
            kind="build",
            timestamp=effective_build_status_at or timestamp,
            activity=effective_build_activity,
            status=effective_build_status,
            source="status_change",
            details={"previous_status": session.build_status},
        )
        _event(
            session.id,
            "validation_changed",
            f"Build {effective_build_status}",
            {"kind": "build", "status": effective_build_status},
        )
        session.build_status = effective_build_status
        session.build_status_at = effective_build_status_at
    baseline_kind = session.last_green_validation_kind
    baseline_at = session.last_green_validation_at
    baseline_count = session.last_green_changed_files_count
    baseline_preview = session.last_green_changed_files_preview or "[]"
    if effective_test_status == "passed" and test_status_changed:
        baseline_kind = "tests"
        baseline_at = effective_test_status_at or timestamp
        baseline_count = session.changed_files_count
        baseline_preview = session.changed_files_preview or "[]"
    elif effective_lint_status == "passed" and lint_status_changed:
        baseline_kind = "lint"
        baseline_at = effective_lint_status_at or timestamp
        baseline_count = session.changed_files_count
        baseline_preview = session.changed_files_preview or "[]"
    elif effective_build_status == "passed" and build_status_changed:
        baseline_kind = "build"
        baseline_at = effective_build_status_at or timestamp
        baseline_count = session.changed_files_count
        baseline_preview = session.changed_files_preview or "[]"

    changed_since_green = bool(session.changed_since_green_validation)
    drift_reason = session.changed_since_green_reason
    baseline_changed = (
        baseline_kind != session.last_green_validation_kind
        or baseline_at != session.last_green_validation_at
        or baseline_count != session.last_green_changed_files_count
        or baseline_preview != (session.last_green_changed_files_preview or "[]")
    )
    if baseline_changed:
        _record_validation_baseline(
            session.id,
            kind=baseline_kind,
            timestamp=baseline_at,
            changed_files_count=baseline_count,
            changed_files_preview=baseline_preview,
            changed_since=changed_since_green,
            changed_reason=drift_reason,
        )
        session.last_green_validation_kind = baseline_kind
        session.last_green_validation_at = baseline_at
        session.last_green_changed_files_count = baseline_count
        session.last_green_changed_files_preview = baseline_preview
    session.needs_attention = 1 if needs_attention else 0


def _refresh_validation_drift(session) -> None:
    if not session.last_green_validation_at:
        next_changed_since = False
        next_reason = None
    else:
        next_changed_since = not (
            session.changed_files_count == session.last_green_changed_files_count
            and (session.changed_files_preview or "[]") == (session.last_green_changed_files_preview or "[]")
        )
        if next_changed_since and session.changed_files_count > 0:
            next_reason = "code changed since the last green validation"
        else:
            next_changed_since = False
            next_reason = None

    if (
        next_changed_since == bool(session.changed_since_green_validation)
        and next_reason == session.changed_since_green_reason
    ):
        return

    _record_validation_baseline(
        session.id,
        kind=session.last_green_validation_kind,
        timestamp=session.last_green_validation_at,
        changed_files_count=session.last_green_changed_files_count,
        changed_files_preview=session.last_green_changed_files_preview or "[]",
        changed_since=next_changed_since,
        changed_reason=next_reason,
    )
    _event(
        session.id,
        "validation_drift_changed",
        "Validation drift detected" if next_changed_since else "Validation drift cleared",
        {
            "changed_since_green_validation": next_changed_since,
            "changed_since_green_reason": next_reason,
            "last_green_validation_kind": session.last_green_validation_kind,
            "last_green_validation_at": session.last_green_validation_at,
        },
    )
    session.changed_since_green_validation = 1 if next_changed_since else 0
    session.changed_since_green_reason = next_reason


def _refresh_validation_coverage(session) -> None:
    policy_state, policy_reason, missing_checks, optional_checks = validation_policy_state(
        session.validation_recipe_json,
        test_status=session.test_status,
        lint_status=session.lint_status,
        build_status=session.build_status,
    )
    if missing_checks and session.changed_files_count > 0:
        coverage_reason = f"required recipe checks not yet observed: {', '.join(missing_checks)}"
    elif missing_checks:
        coverage_reason = f"recipe expects checks not yet observed: {', '.join(missing_checks)}"
    elif optional_checks:
        coverage_reason = f"only optional checks remain: {', '.join(optional_checks)}"
    else:
        coverage_reason = "all expected recipe checks have been observed" if session.validation_recipe_id else None
    missing_checks_json = json.dumps(missing_checks)
    optional_checks_json = json.dumps(optional_checks)
    if (
        missing_checks_json == (session.missing_validation_checks_json or "[]")
        and optional_checks_json == (session.optional_validation_checks_json or "[]")
        and policy_state == (session.validation_policy_state or "unknown")
        and policy_reason == session.validation_policy_reason
        and coverage_reason == session.validation_coverage_reason
    ):
        return
    _record_validation_coverage(
        session.id,
        missing_checks_json=missing_checks_json,
        optional_checks_json=optional_checks_json,
        policy_state=policy_state,
        policy_reason=policy_reason,
        coverage_reason=coverage_reason,
    )
    _event(
        session.id,
        "validation_coverage_changed",
        "Validation recipe coverage updated",
        {
            "missing_checks": missing_checks,
            "optional_checks": optional_checks,
            "validation_policy_state": policy_state,
            "validation_policy_reason": policy_reason,
            "validation_coverage_reason": coverage_reason,
        },
    )
    session.missing_validation_checks_json = missing_checks_json
    session.optional_validation_checks_json = optional_checks_json
    session.validation_policy_state = policy_state
    session.validation_policy_reason = policy_reason
    session.validation_coverage_reason = coverage_reason


def _refresh_review_readiness(session) -> None:
    snapshot = assess_review_readiness(
        status=session.status,
        validation_policy_state=session.validation_policy_state,
        changed_since_green_validation=session.changed_since_green_validation,
        repo_risk_label=session.repo_risk_label,
        repo_risk_reason=session.repo_risk_reason,
        block_reason=session.block_reason,
    )
    if (
        snapshot.state == (session.review_readiness_state or "unknown")
        and snapshot.reason == session.review_readiness_reason
    ):
        return
    _record_review_readiness(session.id, state=snapshot.state, reason=snapshot.reason)
    _event(
        session.id,
        "review_readiness_changed",
        f"Review readiness -> {snapshot.state}",
        {
            "review_readiness_state": snapshot.state,
            "review_readiness_reason": snapshot.reason,
        },
    )
    session.review_readiness_state = snapshot.state
    session.review_readiness_reason = snapshot.reason


def _refresh_completion_state(session) -> None:
    snapshot = assess_completion_state(
        status=session.status,
        review_readiness_state=session.review_readiness_state,
        review_readiness_reason=session.review_readiness_reason,
    )
    if (
        snapshot.state == (session.completion_state or "unknown")
        and snapshot.reason == session.completion_reason
    ):
        return
    _record_completion_state(session.id, state=snapshot.state, reason=snapshot.reason)
    _event(
        session.id,
        "completion_state_changed",
        f"Completion state -> {snapshot.state}",
        {
            "completion_state": snapshot.state,
            "completion_reason": snapshot.reason,
        },
    )
    session.completion_state = snapshot.state
    session.completion_reason = snapshot.reason


def _refresh_work_phase(session, lines: list[str]) -> None:
    snapshot = infer_work_phase(
        lines=lines,
        session_status=session.status,
        changed_files_count=session.changed_files_count,
        test_activity=session.test_activity,
        test_status=session.test_status,
        lint_activity=session.lint_activity,
        lint_status=session.lint_status,
        current_phase=session.work_phase,
        current_confidence=session.work_phase_confidence,
    )
    current_phase = session.work_phase or PHASE_UNKNOWN
    current_confidence = session.work_phase_confidence or "low"
    current_reason = session.work_phase_reason
    current_block_category = session.block_category
    current_block_reason = session.block_reason
    last_major_missing = not session.last_major_phase or session.last_major_phase == PHASE_UNKNOWN
    if (
        snapshot.phase == current_phase
        and snapshot.confidence == current_confidence
        and snapshot.reason == current_reason
        and snapshot.block_category == current_block_category
        and snapshot.block_reason == current_block_reason
        and not (last_major_missing and current_phase in MAJOR_PHASES and current_phase != PHASE_UNKNOWN)
    ):
        return
    last_major_phase = snapshot.phase if snapshot.phase in MAJOR_PHASES and snapshot.phase != PHASE_UNKNOWN else None
    last_major_confidence = snapshot.confidence if last_major_phase else None
    last_major_reason = snapshot.reason if last_major_phase else None
    _record_work_phase(
        session.id,
        snapshot.phase,
        snapshot.confidence,
        reason=snapshot.reason,
        last_major_phase=last_major_phase,
        last_major_phase_confidence=last_major_confidence,
        last_major_phase_reason=last_major_reason,
        block_category=snapshot.block_category,
        block_reason=snapshot.block_reason,
    )
    _event(
        session.id,
        "work_phase_changed",
        f"Phase -> {snapshot.phase}",
        {
            "work_phase": snapshot.phase,
            "confidence": snapshot.confidence,
            "reason": snapshot.reason,
            "block_category": snapshot.block_category,
            "block_reason": snapshot.block_reason,
        },
    )
    session.work_phase = snapshot.phase
    session.work_phase_confidence = snapshot.confidence
    session.work_phase_reason = snapshot.reason
    if last_major_phase:
        session.last_major_phase = last_major_phase
        session.last_major_phase_confidence = last_major_confidence
        session.last_major_phase_reason = last_major_reason
    session.block_category = snapshot.block_category
    session.block_reason = snapshot.block_reason


def _refresh_health(session, idle_age: int | None, idle_threshold_seconds: int) -> None:
    snapshot = assess_session_health(
        status=session.status,
        work_phase=session.work_phase,
        block_category=session.block_category,
        block_reason=session.block_reason,
        repo_risk_label=session.repo_risk_label,
        repo_risk_reason=session.repo_risk_reason,
        test_status=session.test_status,
        lint_status=session.lint_status,
        attachment_state=session.attachment_state,
        changed_since_green_validation=session.changed_since_green_validation,
        last_green_validation_kind=session.last_green_validation_kind,
        missing_validation_checks_count=len(json.loads(session.missing_validation_checks_json or "[]")),
        dirty_start_state=session.dirty_start_state,
        changed_since_start=session.changed_since_start,
        idle_age_seconds=idle_age,
        needs_attention=session.needs_attention,
        idle_threshold_seconds=idle_threshold_seconds,
    )
    if (
        snapshot.score == session.health_score
        and snapshot.label == session.health_label
        and snapshot.reason == session.health_reason
        and snapshot.evidence == session.health_evidence
    ):
        return
    _record_health(session.id, snapshot.score, snapshot.label, snapshot.reason, snapshot.evidence)
    _event(
        session.id,
        "health_changed",
        f"Health -> {snapshot.label}",
        {
            "health_score": snapshot.score,
            "health_label": snapshot.label,
            "health_reason": snapshot.reason,
            "health_evidence": snapshot.evidence,
        },
    )
    session.health_score = snapshot.score
    session.health_label = snapshot.label
    session.health_reason = snapshot.reason
    session.health_evidence = snapshot.evidence


def _refresh_priority(session, idle_age: int | None, idle_threshold_seconds: int) -> None:
    snapshot = assess_session_priority(
        status=session.status,
        work_phase=session.work_phase,
        block_category=session.block_category,
        block_reason=session.block_reason,
        repo_risk_label=session.repo_risk_label,
        repo_risk_reason=session.repo_risk_reason,
        health_label=session.health_label,
        test_status=session.test_status,
        lint_status=session.lint_status,
        attachment_state=session.attachment_state,
        changed_since_green_validation=session.changed_since_green_validation,
        last_green_validation_kind=session.last_green_validation_kind,
        missing_validation_checks_count=len(json.loads(session.missing_validation_checks_json or "[]")),
        dirty_start_state=session.dirty_start_state,
        changed_since_start=session.changed_since_start,
        idle_age_seconds=idle_age,
        needs_attention=session.needs_attention,
        idle_threshold_seconds=idle_threshold_seconds,
    )
    if (
        snapshot.score == session.priority_score
        and snapshot.reason == session.priority_reason
        and snapshot.evidence == session.priority_evidence
    ):
        return
    _record_priority(session.id, snapshot.score, snapshot.reason, snapshot.evidence)
    _event(
        session.id,
        "priority_changed",
        f"Priority -> {snapshot.score}",
        {
            "priority_score": snapshot.score,
            "priority_reason": snapshot.reason,
            "priority_evidence": snapshot.evidence,
        },
    )
    session.priority_score = snapshot.score
    session.priority_reason = snapshot.reason
    session.priority_evidence = snapshot.evidence

def _parse_preview_list(raw_preview) -> set[str]:
    if not raw_preview:
        return set()
    if isinstance(raw_preview, str):
        try:
            parsed = json.loads(raw_preview)
        except json.JSONDecodeError:
            return set()
    else:
        parsed = raw_preview
    if not isinstance(parsed, list):
        return set()
    return {str(item) for item in parsed if item}


def _changed_files_set(session) -> set[str]:
    return _parse_preview_list(session.changed_files_preview)


def _overlapping_changed_paths(session, repo_peers: list) -> list[str]:
    session_paths = _changed_files_set(session)
    if not session_paths:
        return []
    peer_paths: set[str] = set()
    for peer in repo_peers:
        if peer.id == session.id:
            continue
        peer_paths.update(_changed_files_set(peer))
    return sorted(session_paths & peer_paths)


def _refresh_repo_risk(session, active_repo_peers: int, overlapping_paths: list[str]) -> None:
    snapshot = assess_repo_risk(
        mode=session.mode,
        status=session.status,
        branch=session.branch,
        worktree_path=session.worktree_path,
        changed_files_count=session.changed_files_count,
        allow_write=session.allow_write,
        active_repo_peers=active_repo_peers,
        overlapping_paths=overlapping_paths,
    )
    current_overlap = _parse_preview_list(session.repo_overlap_preview)
    if (
        snapshot.label == session.repo_risk_label
        and snapshot.reason == session.repo_risk_reason
        and sorted(current_overlap) == snapshot.overlap_paths
    ):
        return
    _record_repo_risk(session.id, snapshot.label, snapshot.reason)
    _record_repo_overlap(session.id, snapshot.overlap_paths)
    _event(
        session.id,
        "repo_risk_changed",
        f"Repo risk -> {snapshot.label}",
        {
            "repo_risk_label": snapshot.label,
            "repo_risk_reason": snapshot.reason,
            "repo_overlap_paths": snapshot.overlap_paths,
        },
    )
    session.repo_risk_label = snapshot.label
    session.repo_risk_reason = snapshot.reason
    session.repo_overlap_count = len(snapshot.overlap_paths)
    session.repo_overlap_preview = json.dumps(snapshot.overlap_paths[:10])


def _refresh_repo_policy(session) -> None:
    policy_payload = parse_repo_policy(session.repo_policy_json)
    snapshot = assess_repo_policy(
        branch=session.branch,
        allow_write=session.allow_write,
        worktree_path=session.worktree_path,
        protected_branches=policy_payload.get("protected_branches"),
        require_worktree_for_write=bool(policy_payload.get("require_worktree_for_write", False)),
    )
    if (
        snapshot.protected_branch_state == (session.protected_branch_state or "clear")
        and snapshot.protected_branch_reason == session.protected_branch_reason
        and snapshot.isolation_state == (session.isolation_state or "not_required")
        and snapshot.isolation_reason == session.isolation_reason
    ):
        return
    _record_repo_policy(
        session.id,
        protected_branch_state=snapshot.protected_branch_state,
        protected_branch_reason=snapshot.protected_branch_reason,
        isolation_state=snapshot.isolation_state,
        isolation_reason=snapshot.isolation_reason,
    )
    _event(
        session.id,
        "repo_policy_changed",
        "Repo policy signals updated",
        {
            "protected_branch_state": snapshot.protected_branch_state,
            "protected_branch_reason": snapshot.protected_branch_reason,
            "isolation_state": snapshot.isolation_state,
            "isolation_reason": snapshot.isolation_reason,
        },
    )
    session.protected_branch_state = snapshot.protected_branch_state
    session.protected_branch_reason = snapshot.protected_branch_reason
    session.isolation_state = snapshot.isolation_state
    session.isolation_reason = snapshot.isolation_reason


def _refresh_repo_baseline(session) -> None:
    snapshot = assess_repo_baseline(
        initial_changed_files_count=session.initial_changed_files_count,
        initial_changed_files_preview=session.initial_changed_files_preview,
        changed_files_count=session.changed_files_count,
        changed_files_preview=session.changed_files_preview,
    )
    if (
        snapshot.dirty_start_state == (session.dirty_start_state or "clean")
        and snapshot.dirty_start_reason == session.dirty_start_reason
        and snapshot.changed_since_start == int(session.changed_since_start or 0)
        and snapshot.changed_since_start_reason == session.changed_since_start_reason
    ):
        return
    _record_repo_baseline(
        session.id,
        dirty_start_state=snapshot.dirty_start_state,
        dirty_start_reason=snapshot.dirty_start_reason,
        changed_since_start=snapshot.changed_since_start,
        changed_since_start_reason=snapshot.changed_since_start_reason,
    )
    _event(
        session.id,
        "repo_baseline_changed",
        "Repo baseline signals updated",
        {
            "dirty_start_state": snapshot.dirty_start_state,
            "dirty_start_reason": snapshot.dirty_start_reason,
            "changed_since_start": snapshot.changed_since_start,
            "changed_since_start_reason": snapshot.changed_since_start_reason,
        },
    )
    session.dirty_start_state = snapshot.dirty_start_state
    session.dirty_start_reason = snapshot.dirty_start_reason
    session.changed_since_start = snapshot.changed_since_start
    session.changed_since_start_reason = snapshot.changed_since_start_reason


def _refresh_codex_session_link(session, client: RunnerClient) -> None:
    if session.provider != "codex" or session.mode != "managed" or session.codex_session_id or not session.cwd:
        return
    try:
        codex_session_id = client.find_recent_codex_session(
            session.cwd,
            session.prompt,
            session.started_at or session.created_at,
        )
    except RunnerError:
        return
    if not codex_session_id:
        return

    thread = next(
        (
            item
            for item in client.list_resume_candidates(codex_session_id, session.cwd, session.prompt, limit=1)
            if item.get("id") == codex_session_id
        ),
        None,
    )
    _record_codex_history_target(
        session.id,
        codex_session_id,
        str(thread.get("rollout_path")) if thread and thread.get("rollout_path") else None,
        int(thread.get("updated_at")) if thread and thread.get("updated_at") is not None else None,
    )
    _event(
        session.id,
        "codex_session_linked",
        "Linked Codex history session",
        {
            "codex_session_id": codex_session_id,
            "codex_rollout_path": thread.get("rollout_path") if thread else None,
            "codex_updated_at": thread.get("updated_at") if thread else None,
        },
    )
    session.codex_session_id = codex_session_id
    if thread:
        session.codex_rollout_path = str(thread.get("rollout_path")) if thread.get("rollout_path") else None
        session.codex_updated_at = int(thread.get("updated_at")) if thread.get("updated_at") is not None else None


def _backfill_codex_history_target(session, client: RunnerClient) -> None:
    if session.provider != "codex" or not session.codex_session_id:
        return
    if session.codex_rollout_path and session.codex_updated_at is not None:
        return

    try:
        thread = next(
            (
                item
                for item in client.list_resume_candidates(session.codex_session_id, session.cwd, session.prompt, limit=1)
                if item.get("id") == session.codex_session_id
            ),
            None,
        )
    except RunnerError:
        return
    if not thread:
        return

    rollout_path = str(thread.get("rollout_path")) if thread.get("rollout_path") else None
    updated_at = int(thread.get("updated_at")) if thread.get("updated_at") is not None else None
    if rollout_path == session.codex_rollout_path and updated_at == session.codex_updated_at:
        return

    _record_codex_history_target(session.id, session.codex_session_id, rollout_path, updated_at)
    _event(
        session.id,
        "codex_history_backfilled",
        "Codex history target metadata backfilled",
        {
            "codex_session_id": session.codex_session_id,
            "codex_rollout_path": rollout_path,
            "codex_updated_at": updated_at,
        },
    )
    session.codex_rollout_path = rollout_path
    session.codex_updated_at = updated_at



def reconcile_once(runner: RunnerClient | None = None) -> int:
    settings = load_settings()
    client = runner or get_runner_client()
    touched = 0
    sessions = list_sessions()
    active_repo_counts: dict[str, int] = {}
    live_repo_sessions: dict[str, list] = {}
    for session in sessions:
        is_live_repo_peer = session.status in LIVE_REPO_STATUSES or session.attachment_state == "attached"
        if is_live_repo_peer:
            active_repo_counts[session.repo_path] = active_repo_counts.get(session.repo_path, 0) + 1
            live_repo_sessions.setdefault(session.repo_path, []).append(session)
    for session in sessions:
        session = refresh_git_state(session, runner=client)
        _refresh_repo_baseline(session)
        _refresh_repo_policy(session)
        peer_count = active_repo_counts.get(session.repo_path, 0)
        if session.status in LIVE_REPO_STATUSES or session.attachment_state == "attached":
            peer_count = max(0, peer_count - 1)
        overlapping_paths = _overlapping_changed_paths(session, live_repo_sessions.get(session.repo_path, []))
        _refresh_repo_risk(session, peer_count, overlapping_paths)
        attachment_changed = False
        _backfill_codex_history_target(session, client)

        if session.status in {SessionStatus.FINISHED.value, SessionStatus.FAILED.value, SessionStatus.STOPPED.value}:
            _refresh_health(session, None, settings.monitor_idle_seconds)
            _refresh_priority(session, None, settings.monitor_idle_seconds)
            continue

        tmux_ok = bool(session.tmux_session and client.session_exists(session.tmux_session))
        if not tmux_ok and session.mode == "managed":
            if session.started_at is None and (session.attachment_state or "detached") == "detached":
                _refresh_health(session, None, settings.monitor_idle_seconds)
                _refresh_priority(session, None, settings.monitor_idle_seconds)
                continue
            if (session.attachment_state or "detached") != "detached":
                timestamp = datetime.now(UTC).replace(microsecond=0).isoformat()
                _record_attachment_state(session.id, "detached", timestamp)
                _event(
                    session.id,
                    "attachment_changed",
                    "Session detached",
                    {"attachment_state": "detached"},
                )
                session.attachment_state = "detached"
                session.last_detached_at = timestamp
            if session.status != SessionStatus.LOST.value:
                session = update_status(session.id, SessionStatus.LOST, "tmux session missing")
                touched += 1
            _refresh_health(session, None, settings.monitor_idle_seconds)
            _refresh_priority(session, None, settings.monitor_idle_seconds)
            continue

        if tmux_ok and session.tmux_session:
            try:
                attachment_state = "attached" if client.is_session_attached(session.tmux_session) else "detached"
            except RunnerError:
                attachment_state = session.attachment_state or "detached"
            else:
                if attachment_state != (session.attachment_state or "detached"):
                    timestamp = datetime.now(UTC).replace(microsecond=0).isoformat()
                    _record_attachment_state(session.id, attachment_state, timestamp)
                    _event(
                        session.id,
                        "attachment_changed",
                        f"Session {attachment_state}",
                        {"attachment_state": attachment_state},
                    )
                    session.attachment_state = attachment_state
                    attachment_changed = True
                    if attachment_state == "attached":
                        session.last_attached_at = timestamp
                    else:
                        session.last_detached_at = timestamp

        use_log_idle_age = not (tmux_ok and session.tmux_session and session.attachment_state == "attached")
        idle_age = _file_age_seconds(session.log_path) if use_log_idle_age else None
        lines: list[str] = []
        if tmux_ok and session.tmux_session:
            try:
                lines = client.capture_pane(session.tmux_session, tail=40)
            except Exception:
                lines = []
            fingerprint = _pane_fingerprint(lines)
            attach_age = _iso_age_seconds(session.last_attached_at)
            attach_grace_active = (
                session.attachment_state == "attached"
                and attach_age is not None
                and attach_age < ATTACH_ACTIVITY_GRACE_SECONDS
            )
            if fingerprint and fingerprint != session.output_fingerprint and (attachment_changed or attach_grace_active):
                _record_output_fingerprint(session.id, fingerprint)
                session.output_fingerprint = fingerprint
            elif fingerprint and fingerprint != session.output_fingerprint:
                observed_at = datetime.now(UTC).replace(microsecond=0).isoformat()
                _record_output_observation(session.id, fingerprint, observed_at)
                session.output_fingerprint = fingerprint
                session.output_observed_at = observed_at
                idle_age = 0
            else:
                pane_idle_age = _iso_age_seconds(session.output_observed_at)
                idle_age = _min_age(idle_age, pane_idle_age)
        else:
            log_path = Path(session.log_path)
            if log_path.exists():
                lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-40:]

        if lines:
            _refresh_validation_state(session, lines)
        _refresh_validation_drift(session)
        _refresh_validation_coverage(session)
        _refresh_work_phase(session, lines)
        _refresh_review_readiness(session)
        _refresh_completion_state(session)
        _refresh_codex_session_link(session, client)
        if idle_age is None:
            _refresh_health(session, None, settings.monitor_idle_seconds)
            _refresh_priority(session, None, settings.monitor_idle_seconds)
            continue

        if idle_age >= settings.monitor_idle_seconds and session.status not in {SessionStatus.IDLE.value, SessionStatus.WAITING_INPUT.value}:
            session = update_status(session.id, SessionStatus.IDLE, f"Idle for {idle_age}s")
            touched += 1
        elif idle_age < settings.monitor_idle_seconds and session.status in {SessionStatus.CREATED.value, SessionStatus.STARTING.value, SessionStatus.IDLE.value}:
            session = update_status(session.id, SessionStatus.RUNNING, "Recent output detected")
            touched += 1

        _refresh_health(session, idle_age, settings.monitor_idle_seconds)
        _refresh_priority(session, idle_age, settings.monitor_idle_seconds)

    return touched

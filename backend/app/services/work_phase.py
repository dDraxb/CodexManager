from __future__ import annotations

import re
from dataclasses import dataclass

from app.models.session import SessionStatus
from app.services.validation import ACTIVITY_ACTIVE

PHASE_UNKNOWN = "unknown"
PHASE_PLANNING = "planning"
PHASE_READING = "reading"
PHASE_EDITING = "editing"
PHASE_TESTING = "testing"
PHASE_BLOCKED = "blocked"
PHASE_WAITING_INPUT = "waiting_input"
PHASE_REVIEWING = "reviewing"
PHASE_COMPLETED = "completed"

CONFIDENCE_LOW = "low"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_HIGH = "high"

BLOCK_CATEGORY_APPROVAL = "approval"
BLOCK_CATEGORY_INPUT = "input"
BLOCK_CATEGORY_ENVIRONMENT = "environment"
BLOCK_CATEGORY_DEPENDENCY = "dependency"
BLOCK_CATEGORY_NETWORK = "network"
BLOCK_CATEGORY_FILESYSTEM = "filesystem"
BLOCK_CATEGORY_TOOLING = "tooling"
BLOCK_CATEGORY_UNKNOWN = "unknown"

PLANNING_PATTERNS = (
    re.compile(r"\bi(?:'| a)?m (?:going to|treating this as|checking|inspecting|reading)\b", re.IGNORECASE),
    re.compile(r"\btreating this as\b", re.IGNORECASE),
    re.compile(r"\binspect(?:ing)? the codebase\b", re.IGNORECASE),
    re.compile(r"\bnext (?:i('| a)?ll|step)\b", re.IGNORECASE),
    re.compile(r"\bplan\b", re.IGNORECASE),
    re.compile(r"\bfind the relevant integration point\b", re.IGNORECASE),
)

READING_PATTERNS = (
    re.compile(r"\breading (?:the )?(?:code|codebase|repo|repository|docs|documentation|files?)\b", re.IGNORECASE),
    re.compile(r"\binspecting\b", re.IGNORECASE),
    re.compile(r"\blooking through\b", re.IGNORECASE),
    re.compile(r"\bchecking (?:the )?(?:repo|code|implementation)\b", re.IGNORECASE),
)

EDITING_PATTERNS = (
    re.compile(r"\b(?:updated|changed|edited|added|implemented|refactored|rewrote|wired)\b", re.IGNORECASE),
    re.compile(r"\b(?:apply_patch|patching|writing)\b", re.IGNORECASE),
    re.compile(r"\b(?:created|modified)\s+\S+", re.IGNORECASE),
)

REVIEWING_PATTERNS = (
    re.compile(r"\breview(?:ing)?\b", re.IGNORECASE),
    re.compile(r"\bverif(?:y|ying|ied)\b", re.IGNORECASE),
    re.compile(r"\bdouble-check(?:ing)?\b", re.IGNORECASE),
    re.compile(r"\bsanity check\b", re.IGNORECASE),
)

WAITING_INPUT_PATTERNS = (
    re.compile(r"\bdo you want\b", re.IGNORECASE),
    re.compile(r"\bneed your approval\b", re.IGNORECASE),
    re.compile(r"\bpress enter to continue\b", re.IGNORECASE),
    re.compile(r"\bwaiting for (?:your )?(?:input|approval)\b", re.IGNORECASE),
    re.compile(r"\ballow(?: this)? action\b", re.IGNORECASE),
)

BLOCKED_PATTERNS = (
    re.compile(r"\bblocked on\b", re.IGNORECASE),
    re.compile(r"\bmissing (?:dependency|dependencies|config|configuration|env|environment variable)\b", re.IGNORECASE),
    re.compile(r"\bpermission denied\b", re.IGNORECASE),
    re.compile(r"\bcommand not found\b", re.IGNORECASE),
    re.compile(r"\bmodule not found\b", re.IGNORECASE),
    re.compile(r"\bno such file or directory\b", re.IGNORECASE),
    re.compile(r"\bconnection refused\b", re.IGNORECASE),
    re.compile(r"\bunable to connect\b", re.IGNORECASE),
)

TESTING_PATTERNS = (
    re.compile(r"\bpytest\b"),
    re.compile(r"\b(?:npm|pnpm|yarn)\s+(?:run\s+)?test\b"),
    re.compile(r"\b(?:npm|pnpm|yarn)\s+(?:run\s+)?lint\b"),
    re.compile(r"\b(?:ruff|eslint|mypy|flake8|phpstan)\b"),
    re.compile(r"\bsmoke_test\.sh\b"),
    re.compile(r"\bsmoke test\b", re.IGNORECASE),
    re.compile(r"\b\d+\s+passed\b", re.IGNORECASE),
    re.compile(r"\bsmoke test succeeded\b", re.IGNORECASE),
)

COMPLETED_PATTERNS = (
    re.compile(r"\ball requested changes are complete\b", re.IGNORECASE),
    re.compile(r"\bcompleted successfully\b", re.IGNORECASE),
    re.compile(r"\bbuild passed\b", re.IGNORECASE),
    re.compile(r"\bsmoke test succeeded\b", re.IGNORECASE),
)

ACTIVE_SESSION_STATUSES = {
    SessionStatus.RUNNING.value,
    SessionStatus.STARTING.value,
    SessionStatus.WAITING_INPUT.value,
}


@dataclass(frozen=True, slots=True)
class WorkPhaseSnapshot:
    phase: str
    confidence: str
    reason: str | None
    block_category: str | None
    block_reason: str | None


def _extract_block_details(stripped: str) -> tuple[str | None, str | None]:
    lowered = stripped.lower()
    if "waiting for" in lowered and "approval" in lowered:
        return BLOCK_CATEGORY_APPROVAL, "awaiting approval"
    if "waiting for" in lowered and "input" in lowered:
        return BLOCK_CATEGORY_INPUT, "awaiting input"
    if "approve" in lowered or "approval" in lowered:
        return BLOCK_CATEGORY_APPROVAL, "awaiting approval"
    if "missing" in lowered and ("environment variable" in lowered or "env" in lowered):
        return BLOCK_CATEGORY_ENVIRONMENT, "missing environment configuration"
    if "missing" in lowered and ("config" in lowered or "configuration" in lowered):
        return BLOCK_CATEGORY_ENVIRONMENT, "missing environment configuration"
    if "missing" in lowered and ("dependency" in lowered or "dependencies" in lowered):
        return BLOCK_CATEGORY_DEPENDENCY, "missing dependency"
    if "permission denied" in lowered:
        return BLOCK_CATEGORY_FILESYSTEM, "permission denied"
    if "command not found" in lowered:
        return BLOCK_CATEGORY_TOOLING, "command not found"
    if "module not found" in lowered:
        return BLOCK_CATEGORY_DEPENDENCY, "missing module"
    if "no such file or directory" in lowered:
        return BLOCK_CATEGORY_FILESYSTEM, "missing file or directory"
    if "connection refused" in lowered or "unable to connect" in lowered:
        return BLOCK_CATEGORY_NETWORK, "connection failure"
    if "blocked on" in lowered:
        return BLOCK_CATEGORY_UNKNOWN, stripped
    return None, None


def _latest_matching_phase(lines: list[str]) -> tuple[str, str, str | None, str | None]:
    latest_index = -1
    latest_phase = PHASE_UNKNOWN
    latest_confidence = CONFIDENCE_LOW
    latest_block_category = None
    latest_block_reason = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        phase = PHASE_UNKNOWN
        confidence = CONFIDENCE_LOW
        block_category = None
        block_reason = None
        if any(pattern.search(stripped) for pattern in WAITING_INPUT_PATTERNS):
            phase = PHASE_WAITING_INPUT
            confidence = CONFIDENCE_HIGH
            block_category = BLOCK_CATEGORY_INPUT
            block_reason = "awaiting approval or input"
        elif any(pattern.search(stripped) for pattern in BLOCKED_PATTERNS):
            phase = PHASE_BLOCKED
            confidence = CONFIDENCE_HIGH
            block_category, block_reason = _extract_block_details(stripped)
        elif any(pattern.search(stripped) for pattern in TESTING_PATTERNS):
            phase = PHASE_TESTING
            confidence = CONFIDENCE_HIGH
        elif any(pattern.search(stripped) for pattern in COMPLETED_PATTERNS):
            phase = PHASE_COMPLETED
            confidence = CONFIDENCE_HIGH
        elif any(pattern.search(stripped) for pattern in REVIEWING_PATTERNS):
            phase = PHASE_REVIEWING
            confidence = CONFIDENCE_MEDIUM
        elif any(pattern.search(stripped) for pattern in EDITING_PATTERNS):
            phase = PHASE_EDITING
            confidence = CONFIDENCE_MEDIUM
        elif any(pattern.search(stripped) for pattern in READING_PATTERNS):
            phase = PHASE_READING
            confidence = CONFIDENCE_MEDIUM
        elif any(pattern.search(stripped) for pattern in PLANNING_PATTERNS):
            phase = PHASE_PLANNING
            confidence = CONFIDENCE_MEDIUM
        if phase != PHASE_UNKNOWN:
            latest_index = index
            latest_phase = phase
            latest_confidence = confidence
            latest_block_category = block_category
            latest_block_reason = block_reason
    if latest_index >= 0:
        return latest_phase, latest_confidence, latest_block_category, latest_block_reason
    return PHASE_UNKNOWN, CONFIDENCE_LOW, None, None


def _bump_confidence(confidence: str) -> str:
    if confidence == CONFIDENCE_LOW:
        return CONFIDENCE_MEDIUM
    if confidence == CONFIDENCE_MEDIUM:
        return CONFIDENCE_HIGH
    return CONFIDENCE_HIGH


def _phase_label(phase: str) -> str:
    return phase.replace("_", " ")


def _compose_reason(base: str, supporting: list[str]) -> str:
    if not supporting:
        return base
    return f"{base}; supported by {', '.join(supporting)}"


def _matched_phase_reason(
    *,
    phase: str,
    session_status: str,
    changed_files_count: int,
    test_activity: str | None,
    test_status: str | None,
    lint_activity: str | None,
    lint_status: str | None,
) -> str:
    if phase == PHASE_PLANNING:
        base = "recent output looks like planning work"
    elif phase == PHASE_READING:
        base = "recent output looks like code reading or inspection"
    elif phase == PHASE_EDITING:
        base = "recent output references file edits or implementation work"
    elif phase == PHASE_TESTING:
        base = "recent output looks like validation or test work"
    elif phase == PHASE_REVIEWING:
        base = "recent output looks like verification or review work"
    else:
        base = f"recent output looks like {_phase_label(phase)} work"

    supporting: list[str] = []
    if session_status in ACTIVE_SESSION_STATUSES:
        supporting.append("the session is currently active")
    if phase == PHASE_EDITING and changed_files_count > 0:
        supporting.append("the repo already has changed files")
    if phase == PHASE_TESTING and (test_activity == ACTIVITY_ACTIVE or lint_activity == ACTIVITY_ACTIVE):
        supporting.append("validation activity is active now")
    elif phase == PHASE_TESTING and (
        (test_status and test_status != "unknown") or (lint_status and lint_status != "unknown")
    ):
        supporting.append("a recent validation result was observed")
    if phase == PHASE_REVIEWING and changed_files_count > 0:
        supporting.append("the repo has changes to review")
    return _compose_reason(base, supporting)


def _evidence_fused_confidence(
    *,
    phase: str,
    confidence: str,
    session_status: str,
    changed_files_count: int,
    test_activity: str | None,
    test_status: str | None,
    lint_activity: str | None,
    lint_status: str | None,
) -> str:
    if phase in {PHASE_UNKNOWN, PHASE_BLOCKED, PHASE_WAITING_INPUT, PHASE_COMPLETED}:
        return confidence

    evidence_points = 0
    if session_status in ACTIVE_SESSION_STATUSES:
        evidence_points += 1
    if phase == PHASE_EDITING and changed_files_count > 0:
        evidence_points += 1
    if phase == PHASE_TESTING and (test_activity == ACTIVITY_ACTIVE or lint_activity == ACTIVITY_ACTIVE):
        evidence_points += 2
    elif phase == PHASE_TESTING and (
        (test_status and test_status != "unknown") or (lint_status and lint_status != "unknown")
    ):
        evidence_points += 1
    if phase == PHASE_REVIEWING and (
        changed_files_count > 0 or (test_status and test_status != "unknown") or (lint_status and lint_status != "unknown")
    ):
        evidence_points += 1

    fused = confidence
    if evidence_points >= 2:
        fused = _bump_confidence(fused)
    if evidence_points >= 3:
        fused = _bump_confidence(fused)
    return fused


def infer_work_phase(
    *,
    lines: list[str],
    session_status: str,
    changed_files_count: int,
    test_activity: str | None,
    test_status: str | None,
    lint_activity: str | None,
    lint_status: str | None,
    current_phase: str | None,
    current_confidence: str | None,
) -> WorkPhaseSnapshot:
    if session_status == SessionStatus.WAITING_INPUT.value:
        return WorkPhaseSnapshot(
            PHASE_WAITING_INPUT,
            CONFIDENCE_HIGH,
            "session status explicitly indicates it is waiting for approval or input",
            BLOCK_CATEGORY_INPUT,
            "awaiting approval or input",
        )
    if session_status == SessionStatus.FINISHED.value:
        return WorkPhaseSnapshot(
            PHASE_COMPLETED,
            CONFIDENCE_HIGH,
            "session reached a terminal finished state",
            None,
            None,
        )

    phase, confidence, block_category, block_reason = _latest_matching_phase(lines)
    if phase in {PHASE_WAITING_INPUT, PHASE_BLOCKED, PHASE_COMPLETED}:
        if phase == PHASE_BLOCKED:
            reason = f"recent output shows a blocking issue: {block_reason or 'blocking error detected'}"
        elif phase == PHASE_COMPLETED:
            reason = "recent output indicates the work completed successfully"
        else:
            reason = "recent output indicates the session is waiting for approval or input"
        return WorkPhaseSnapshot(phase, confidence, reason, block_category, block_reason)
    if test_activity == ACTIVITY_ACTIVE or lint_activity == ACTIVITY_ACTIVE:
        return WorkPhaseSnapshot(
            PHASE_TESTING,
            CONFIDENCE_HIGH,
            "validation activity is running now",
            None,
            None,
        )
    if (
        changed_files_count > 0
        and session_status in {SessionStatus.RUNNING.value, SessionStatus.STARTING.value}
        and phase in {PHASE_UNKNOWN, PHASE_PLANNING, PHASE_READING}
    ):
        return WorkPhaseSnapshot(
            PHASE_EDITING,
            CONFIDENCE_HIGH,
            "changed files appeared while the session remained active",
            None,
            None,
        )
    if phase != PHASE_UNKNOWN:
        return WorkPhaseSnapshot(
            phase,
            _evidence_fused_confidence(
                phase=phase,
                confidence=confidence,
                session_status=session_status,
                changed_files_count=changed_files_count,
                test_activity=test_activity,
                test_status=test_status,
                lint_activity=lint_activity,
                lint_status=lint_status,
            ),
            _matched_phase_reason(
                phase=phase,
                session_status=session_status,
                changed_files_count=changed_files_count,
                test_activity=test_activity,
                test_status=test_status,
                lint_activity=lint_activity,
                lint_status=lint_status,
            ),
            None,
            None,
        )

    if session_status in {SessionStatus.CREATED.value, SessionStatus.STARTING.value}:
        return WorkPhaseSnapshot(
            PHASE_PLANNING,
            CONFIDENCE_LOW,
            "session is new and has not produced stronger phase evidence yet",
            None,
            None,
        )

    if current_phase and current_phase != PHASE_UNKNOWN:
        return WorkPhaseSnapshot(
            current_phase,
            current_confidence or CONFIDENCE_LOW,
            f"no stronger new evidence appeared, so the previous {_phase_label(current_phase)} assessment is being preserved",
            None,
            None,
        )
    return WorkPhaseSnapshot(PHASE_UNKNOWN, CONFIDENCE_LOW, "not enough recent evidence to infer a stronger work phase", None, None)

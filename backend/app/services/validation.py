from __future__ import annotations

import re
from dataclasses import dataclass


STATUS_UNKNOWN = "unknown"
STATUS_RUNNING = "running"
STATUS_PASSED = "passed"
STATUS_FAILED = "failed"

TEST_COMMAND_PATTERNS = (
    re.compile(r"\bpytest\b"),
    re.compile(r"\bphpunit\b"),
    re.compile(r"\bcargo test\b"),
    re.compile(r"\bgo test\b"),
    re.compile(r"\b(?:npm|pnpm|yarn)\s+(?:run\s+)?test\b"),
    re.compile(r"\bvitest\b"),
    re.compile(r"\bjest\b"),
    re.compile(r"\bsmoke_test\.sh\b"),
    re.compile(r"\bsmoke test\b", re.IGNORECASE),
)

TEST_PASS_PATTERNS = (
    re.compile(r"=+\s+\d+\s+passed(?:,\s*\d+\s+warnings?)?\s+in\s+"),
    re.compile(r"\bOK\s*\(\d+\s+tests?"),
    re.compile(r"test result:\s+ok\.", re.IGNORECASE),
    re.compile(r"^ok\s{1,}\S+", re.IGNORECASE),
    re.compile(r"Tests:\s+.*passed", re.IGNORECASE),
    re.compile(r"\[\d+/\d+\]\s+PASS\b", re.IGNORECASE),
    re.compile(r"Smoke test succeeded", re.IGNORECASE),
)

TEST_FAIL_PATTERNS = (
    re.compile(r"=+\s+.*\bfailed\b.*in\s+"),
    re.compile(r"\bFAILURES\b", re.IGNORECASE),
    re.compile(r"test result:\s+FAILED", re.IGNORECASE),
    re.compile(r"^FAIL\s{1,}\S+", re.IGNORECASE),
    re.compile(r"Tests:\s+.*failed", re.IGNORECASE),
    re.compile(r"\[\d+/\d+\]\s+FAIL\b", re.IGNORECASE),
    re.compile(r"Smoke test failed", re.IGNORECASE),
)

LINT_COMMAND_PATTERNS = (
    re.compile(r"\bruff\b"),
    re.compile(r"\bmypy\b"),
    re.compile(r"\bflake8\b"),
    re.compile(r"\beslint\b"),
    re.compile(r"\bphpstan\b"),
    re.compile(r"\b(?:npm|pnpm|yarn)\s+(?:run\s+)?lint\b"),
)

LINT_PASS_PATTERNS = (
    re.compile(r"All checks passed!", re.IGNORECASE),
    re.compile(r"Success:\s+no issues found", re.IGNORECASE),
    re.compile(r"No issues found", re.IGNORECASE),
    re.compile(r"found\s+0\s+errors", re.IGNORECASE),
    re.compile(r"0\s+problems", re.IGNORECASE),
    re.compile(r"\[OK\]", re.IGNORECASE),
)

LINT_FAIL_PATTERNS = (
    re.compile(r"\bwould reformat\b", re.IGNORECASE),
    re.compile(r"\bFound\s+\d+\s+errors?\b", re.IGNORECASE),
    re.compile(r"\b\d+\s+problems?\b", re.IGNORECASE),
    re.compile(r"\b\d+\s+errors?,\s*\d+\s+warnings?\b", re.IGNORECASE),
    re.compile(r"\[ERROR\]", re.IGNORECASE),
)


@dataclass(frozen=True, slots=True)
class ValidationSnapshot:
    test_status: str
    lint_status: str


def _latest_status(lines: list[str], command_patterns, pass_patterns, fail_patterns) -> str:
    latest_index = -1
    latest_status = STATUS_UNKNOWN
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if any(pattern.search(stripped) for pattern in command_patterns):
            latest_index = index
            latest_status = STATUS_RUNNING
        if any(pattern.search(stripped) for pattern in pass_patterns):
            latest_index = index
            latest_status = STATUS_PASSED
        if any(pattern.search(stripped) for pattern in fail_patterns):
            latest_index = index
            latest_status = STATUS_FAILED
    return latest_status if latest_index >= 0 else STATUS_UNKNOWN


def analyze_validation(lines: list[str]) -> ValidationSnapshot:
    return ValidationSnapshot(
        test_status=_latest_status(lines, TEST_COMMAND_PATTERNS, TEST_PASS_PATTERNS, TEST_FAIL_PATTERNS),
        lint_status=_latest_status(lines, LINT_COMMAND_PATTERNS, LINT_PASS_PATTERNS, LINT_FAIL_PATTERNS),
    )

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime

from app.models.session import SessionRecord
from app.services.handoff import automation_recommendations_for_session, create_handoff
from app.services.sessions import SessionError, create_managed_session, get_session, list_sessions


SPAWN_ACTIONS = {
    "spawn_validation",
    "run_validation_recipe",
    "spawn_review",
    "spawn_investigation",
    "spawn_isolated_followup",
    "resume_or_relaunch",
}
EXECUTABLE_ACTIONS = SPAWN_ACTIONS | {"archive_with_summary"}
ACTIVE_CHILD_STATUSES = {"created", "starting", "running", "waiting_input", "idle"}


def _automation_name(parent: SessionRecord, action: str) -> str:
    suffix = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    action_slug = action.replace("spawn_", "").replace("_", "-")
    return f"{parent.name}-{action_slug}-{suffix}"


def _profile_for_action(parent: SessionRecord, action: str) -> str:
    if action == "spawn_review":
        return "read-only"
    if action in {"spawn_validation", "run_validation_recipe"} and parent.profile == "read-only":
        return "read-only"
    return parent.profile if parent.profile in {"read-only", "safe-edit", "full-agent"} else "safe-edit"


def _prompt_for_action(parent: SessionRecord, action: str, label: str, reason: str, resume_brief: str) -> str:
    action_guidance = {
        "spawn_validation": "Run the repo's relevant validation checks. Fix only narrow validation failures that are clearly in scope, then report exact commands and results.",
        "run_validation_recipe": "Run the configured validation recipe for this repo. If a required check fails, investigate and fix only directly related failures.",
        "spawn_review": "Review the completed work. Do not edit files unless explicitly necessary. Report findings first with file and line references.",
        "spawn_investigation": "Investigate the blocker, identify the root cause, and either make a scoped fix or produce a precise unblock plan.",
        "spawn_isolated_followup": "Continue the work in an isolated worktree/session, preserving the parent session's context and avoiding unsafe main-branch edits.",
        "resume_or_relaunch": "Recover the failed or lost work, inspect current repo/session state, and continue only if the path is safe.",
    }
    guidance = action_guidance.get(action, "Use the handoff brief to continue the work safely and report the result.")
    return "\n\n".join(
        [
            f"Automation follow-up for parent session {parent.name} ({parent.id}).",
            f"Action: {label or action}",
            f"Reason: {reason or 'No explicit reason recorded.'}",
            guidance,
            "Parent resume brief:",
            resume_brief,
        ]
    )


def execute_automation_action(
    session_id: str,
    *,
    action: str,
    label: str = "",
    reason: str = "",
    launch: bool = True,
) -> dict:
    parent = get_session(session_id)
    if parent is None:
        raise SessionError(f"session '{session_id}' not found")
    if action not in SPAWN_ACTIONS and action != "archive_with_summary":
        raise SessionError(f"automation action '{action}' is not executable")
    existing_child = active_automation_child(parent.id, action)
    if existing_child is not None and action in SPAWN_ACTIONS:
        return {
            "action": action,
            "parentSession": asdict(parent),
            "handoff": None,
            "spawnedSession": asdict(existing_child),
            "launch": False,
            "duplicateSuppressed": True,
        }

    matching_recommendation = next(
        (item for item in automation_recommendations_for_session(parent) if item.get("action") == action),
        None,
    )
    effective_label = label or (matching_recommendation or {}).get("label") or action
    effective_reason = reason or (matching_recommendation or {}).get("reason") or ""
    handoff = create_handoff(
        parent.id,
        kind="archive" if action == "archive_with_summary" else "generated",
        human_notes=f"Automation action: {effective_label}. {effective_reason}".strip(),
    )

    if action == "archive_with_summary":
        return {
            "action": action,
            "parentSession": asdict(parent),
            "handoff": asdict(handoff),
            "spawnedSession": None,
            "launch": False,
        }

    prompt = _prompt_for_action(parent, action, effective_label, effective_reason, handoff.resume_brief)
    spawned = create_managed_session(
        name=_automation_name(parent, action),
        repo_path=parent.repo_path,
        profile=_profile_for_action(parent, action),
        prompt=prompt,
        approval_policy=parent.approval_policy or "on-request",
        create_worktree_for_writes=action == "spawn_isolated_followup",
        auto_init_git=False,
        require_changelog=bool(parent.require_changelog),
        parent_session_id=parent.id,
        automation_action=action,
        launch=launch,
        defer_launch=True,
    )
    return {
        "action": action,
        "parentSession": asdict(parent),
        "handoff": asdict(handoff),
        "spawnedSession": asdict(spawned),
        "launch": launch,
        "prompt": prompt,
        "duplicateSuppressed": False,
    }


def active_automation_child(parent_session_id: str, action: str) -> SessionRecord | None:
    for session in list_sessions():
        if (
            session.parent_session_id == parent_session_id
            and session.automation_action == action
            and session.status in ACTIVE_CHILD_STATUSES
        ):
            return session
    return None


def automation_queue(
    *,
    min_priority: int = 0,
    executable_only: bool = False,
    include_archived: bool = True,
    limit: int = 50,
) -> dict:
    items: list[dict] = []
    archived_statuses = {"finished", "failed", "stopped", "lost"}
    for session in list_sessions():
        if not include_archived and session.status in archived_statuses:
            continue
        for recommendation in automation_recommendations_for_session(session):
            priority = int(recommendation.get("priority") or 0)
            action = str(recommendation.get("action") or "")
            executable = action in EXECUTABLE_ACTIONS
            duplicate_child = active_automation_child(session.id, action) if executable else None
            if priority < min_priority:
                continue
            if duplicate_child is not None:
                continue
            if executable_only and not executable:
                continue
            items.append(
                {
                    "session": asdict(session),
                    "recommendation": recommendation,
                    "priority": priority,
                    "executable": executable,
                }
            )
    items.sort(
        key=lambda item: (
            int(item["priority"]),
            str(item["session"].get("updated_at") or ""),
        ),
        reverse=True,
    )
    return {
        "items": items[:limit],
        "count": min(len(items), limit),
        "totalCandidates": len(items),
        "filters": {
            "minPriority": min_priority,
            "executableOnly": executable_only,
            "includeArchived": include_archived,
            "limit": limit,
        },
    }


def execute_next_automation(
    *,
    min_priority: int = 80,
    launch: bool = True,
    include_archived: bool = True,
) -> dict:
    queue = automation_queue(
        min_priority=min_priority,
        executable_only=True,
        include_archived=include_archived,
        limit=1,
    )
    if not queue["items"]:
        raise SessionError("no executable automation recommendations match the requested priority")
    item = queue["items"][0]
    recommendation = item["recommendation"]
    session = item["session"]
    result = execute_automation_action(
        str(session["id"]),
        action=str(recommendation["action"]),
        label=str(recommendation.get("label") or ""),
        reason=str(recommendation.get("reason") or ""),
        launch=launch,
    )
    return {
        "selected": item,
        "result": result,
    }

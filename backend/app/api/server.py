from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.monitoring.reconciler import reconcile_once
from app.services.automation import automation_queue, execute_automation_action, execute_next_automation, sweep_automation
from app.services.codex_config_presets import (
    apply_codex_config_preset as apply_codex_config_preset_payload,
    delete_codex_config_preset,
    list_manager_codex_config_presets,
    list_saved_codex_config_presets,
    preview_apply_codex_config_preset,
    save_codex_config_preset,
)
from app.services.manager_rules import (
    ManagerRulesError,
    effective_session_defaults,
    preview_manager_rule_matches,
    read_manager_rules,
    restore_manager_rules,
    write_manager_rules,
)
from app.services.codex_mcp import describe_codex_mcp_dependencies
from app.services.handoff import automation_snapshot, create_handoff, list_handoffs
from app.services.history import compare_repo_sessions, search_session_history, session_analytics
from app.services.history_views import HistoryViewError, delete_history_view, list_history_views, save_history_view
from app.services.repo_policy_rules import list_repo_policies
from app.services.validation_recipe import list_manager_validation_presets
from app.services.sessions import (
    SessionError,
    adopt_session,
    capture_session_logs,
    create_managed_session,
    delete_session,
    delete_stopped_sessions,
    delete_test_named_sessions,
    get_session,
    list_events,
    list_sessions,
    list_validation_history,
    open_session,
    resume_session,
    set_codex_session_id,
    stop_session,
)
from app.runner.client import get_runner_client
from app.runner.contracts import RunnerError

app = FastAPI(title="codex-session-manager")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_RECONCILE_MIN_INTERVAL_SECONDS = 2.0
_reconcile_lock = threading.Lock()
_last_reconcile_monotonic = 0.0
_reconcile_in_progress = False


def _run_reconcile(*, suppress_errors: bool = False) -> None:
    global _last_reconcile_monotonic, _reconcile_in_progress

    try:
        try:
            reconcile_once()
        except Exception:
            if not suppress_errors:
                raise
        else:
            _last_reconcile_monotonic = time.monotonic()
    finally:
        _reconcile_in_progress = False


def _reconcile_if_stale(force: bool = False, background: bool = False) -> None:
    global _last_reconcile_monotonic, _reconcile_in_progress

    now = time.monotonic()
    if not force and now - _last_reconcile_monotonic < _RECONCILE_MIN_INTERVAL_SECONDS:
        return

    with _reconcile_lock:
        now = time.monotonic()
        if not force and now - _last_reconcile_monotonic < _RECONCILE_MIN_INTERVAL_SECONDS:
            return
        if _reconcile_in_progress:
            return
        _reconcile_in_progress = True
        if background:
            threading.Thread(target=lambda: _run_reconcile(suppress_errors=True), daemon=True).start()
            return
        _run_reconcile()


class StartRequest(BaseModel):
    name: str
    repo_path: str | None = Field(default=None, alias="repoPath")
    profile: str = "safe-edit"
    prompt: str | None = None
    approval_policy: str = Field(default="on-request", alias="approvalPolicy")
    create_worktree_for_writes: bool = Field(default=False, alias="createWorktreeForWrites")
    auto_init_git: bool = Field(default=False, alias="autoInitGit")
    require_changelog: bool = Field(default=False, alias="requireChangelog")
    launch: bool = True
    manager_defaults_fields: list[str] = Field(default_factory=list, alias="managerDefaultsFields")


class AdoptRequest(BaseModel):
    name: str
    codex_session_id: str = Field(alias="codexSessionId")
    repo_path: str = Field(alias="repoPath")
    profile: str = "read-only"


class CodexSessionLinkRequest(BaseModel):
    codex_session_id: str = Field(alias="codexSessionId")
    codex_rollout_path: str | None = Field(default=None, alias="codexRolloutPath")
    codex_updated_at: int | None = Field(default=None, alias="codexUpdatedAt")


class ValidationPresetApplyRequest(BaseModel):
    repo_path: str = Field(alias="repoPath")
    preset_id: str = Field(alias="presetId")


class CodexConfigPresetApplyRequest(BaseModel):
    preset_id: str = Field(alias="presetId")
    scope: str
    repo_path: str | None = Field(default=None, alias="repoPath")
    mode: str | None = None


class CodexConfigPresetWriteRequest(BaseModel):
    scope: str
    preset_id: str = Field(alias="presetId")
    label: str = ""
    description: str = ""
    content: str
    mode: str = "overlay"
    repo_path: str | None = Field(default=None, alias="repoPath")


class CodexConfigPresetDeleteRequest(BaseModel):
    scope: str
    preset_id: str = Field(alias="presetId")
    repo_path: str | None = Field(default=None, alias="repoPath")


class ValidationRecipeMaterializeRequest(BaseModel):
    repo_path: str = Field(alias="repoPath")
    recipe_json: str = Field(alias="recipeJson")


class CodexSkillCreateRequest(BaseModel):
    scope: str
    name: str
    summary: str = ""
    repo_path: str | None = Field(default=None, alias="repoPath")


class CodexSkillWriteRequest(BaseModel):
    scope: str
    name: str
    content: str
    repo_path: str | None = Field(default=None, alias="repoPath")


class CodexSkillRestoreRequest(BaseModel):
    scope: str
    name: str
    backup_path: str = Field(alias="backupPath")
    repo_path: str | None = Field(default=None, alias="repoPath")


class CodexSkillDeleteRequest(BaseModel):
    scope: str
    name: str
    repo_path: str | None = Field(default=None, alias="repoPath")


class CodexSkillCatalogListRequest(BaseModel):
    scope: str
    repo_path: str | None = Field(default=None, alias="repoPath")
    repo: str = "openai/skills"
    path: str = "skills/.curated"
    ref: str = "main"


class CodexSkillCatalogInstallRequest(BaseModel):
    scope: str
    name: str
    repo_path: str | None = Field(default=None, alias="repoPath")
    repo: str = "openai/skills"
    path: str = "skills/.curated"
    ref: str = "main"
    method: str = "auto"


class CodexSkillGithubInstallRequest(BaseModel):
    scope: str
    repo_path: str | None = Field(default=None, alias="repoPath")
    github_repo: str | None = Field(default=None, alias="githubRepo")
    github_url: str | None = Field(default=None, alias="githubUrl")
    github_path: str | None = Field(default=None, alias="githubPath")
    ref: str = "main"
    method: str = "auto"
    name: str | None = None


class CodexPromptWriteRequest(BaseModel):
    scope: str
    name: str
    content: str = ""
    repo_path: str | None = Field(default=None, alias="repoPath")


class CodexPromptRestoreRequest(BaseModel):
    scope: str
    name: str
    backup_path: str = Field(alias="backupPath")
    repo_path: str | None = Field(default=None, alias="repoPath")


class CodexPromptDeleteRequest(BaseModel):
    scope: str
    name: str
    repo_path: str | None = Field(default=None, alias="repoPath")


class CodexConfigWriteRequest(BaseModel):
    scope: str
    content: str
    repo_path: str | None = Field(default=None, alias="repoPath")


class CodexConfigRestoreRequest(BaseModel):
    scope: str
    backup_path: str = Field(alias="backupPath")
    repo_path: str | None = Field(default=None, alias="repoPath")


class CodexConfigStructuredWriteRequest(BaseModel):
    scope: str
    scalar_fields: dict = Field(default_factory=dict, alias="scalarFields")
    advanced_json: str = Field(default="", alias="advancedJson")
    repo_path: str | None = Field(default=None, alias="repoPath")


class CodexRulesWriteRequest(BaseModel):
    scope: str
    content: str
    repo_path: str | None = Field(default=None, alias="repoPath")


class CodexRulesRestoreRequest(BaseModel):
    scope: str
    backup_path: str = Field(alias="backupPath")
    repo_path: str | None = Field(default=None, alias="repoPath")


class ManagerRulesWriteRequest(BaseModel):
    content: str


class ManagerRulesRestoreRequest(BaseModel):
    backup_path: str = Field(alias="backupPath")


class CodexAgentCreateRequest(BaseModel):
    name: str
    summary: str = ""


class CodexAgentConfigWriteRequest(BaseModel):
    name: str
    content: str


class CodexAgentConfigRestoreRequest(BaseModel):
    name: str
    backup_path: str = Field(alias="backupPath")


class CodexMcpCreateRequest(BaseModel):
    scope: str
    name: str
    command: str
    args: list[str] = []
    cwd: str | None = None
    env: dict[str, str] = {}
    repo_path: str | None = Field(default=None, alias="repoPath")


class CodexMcpDeleteRequest(BaseModel):
    scope: str
    name: str
    repo_path: str | None = Field(default=None, alias="repoPath")


class CodexMcpEnabledRequest(BaseModel):
    scope: str
    name: str
    enabled: bool
    repo_path: str | None = Field(default=None, alias="repoPath")


class HandoffCreateRequest(BaseModel):
    kind: str = "generated"
    human_notes: str = Field(default="", alias="humanNotes")


class AutomationExecuteRequest(BaseModel):
    action: str
    label: str = ""
    reason: str = ""
    launch: bool = True


class AutomationExecuteNextRequest(BaseModel):
    min_priority: int = Field(default=80, alias="minPriority")
    launch: bool = True
    include_archived: bool = Field(default=True, alias="includeArchived")


class AutomationSweepRequest(BaseModel):
    min_priority: int = Field(default=80, alias="minPriority")
    max_actions: int = Field(default=3, alias="maxActions")
    launch: bool = True
    include_archived: bool = Field(default=True, alias="includeArchived")


class HistoryViewWriteRequest(BaseModel):
    view_id: str = Field(alias="viewId")
    label: str
    description: str = ""
    filters: dict = Field(default_factory=dict)


class HistoryViewDeleteRequest(BaseModel):
    view_id: str = Field(alias="viewId")


def _session_or_404(session_id: str):
    session = get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return session


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/summary")
def summary() -> dict:
    _reconcile_if_stale(force=True)
    rows = list_sessions()
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1

    return {
        "total": len(rows),
        "counts": counts,
        "needsAttention": len([r for r in rows if r.needs_attention]),
    }


@app.get("/api/sessions")
def sessions() -> list[dict]:
    _reconcile_if_stale(background=True)
    return [asdict(s) for s in list_sessions()]


@app.get("/api/sessions/{session_id}")
def session_detail(session_id: str) -> dict:
    _reconcile_if_stale(background=True)
    return asdict(_session_or_404(session_id))


@app.get("/api/sessions/{session_id}/logs")
def session_logs(session_id: str, tail: int = 200) -> dict:
    _session_or_404(session_id)
    return {"lines": capture_session_logs(session_id, tail=tail)}


@app.get("/api/sessions/{session_id}/events")
def session_events(session_id: str, limit: int = 100) -> list[dict]:
    _session_or_404(session_id)
    return [asdict(e) for e in list_events(session_id, limit)]


@app.get("/api/sessions/{session_id}/validation-history")
def session_validation_history(session_id: str, limit: int = 30) -> list[dict]:
    _session_or_404(session_id)
    return [asdict(entry) for entry in list_validation_history(session_id, limit)]


@app.get("/api/sessions/{session_id}/handoffs")
def session_handoffs(session_id: str, limit: int = 20) -> list[dict]:
    _session_or_404(session_id)
    try:
        return [asdict(row) for row in list_handoffs(session_id, limit=limit)]
    except SessionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/sessions/{session_id}/handoffs")
def session_create_handoff(session_id: str, request: HandoffCreateRequest) -> dict:
    _session_or_404(session_id)
    try:
        return asdict(create_handoff(session_id, kind=request.kind, human_notes=request.human_notes))
    except SessionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/sessions/{session_id}/automation")
def session_automation(session_id: str) -> dict:
    _session_or_404(session_id)
    try:
        return automation_snapshot(session_id)
    except SessionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/sessions/{session_id}/automation/execute")
def session_execute_automation(session_id: str, request: AutomationExecuteRequest) -> dict:
    _session_or_404(session_id)
    try:
        return execute_automation_action(
            session_id,
            action=request.action,
            label=request.label,
            reason=request.reason,
            launch=request.launch,
        )
    except SessionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/history/search")
def history_search(
    query: str | None = None,
    repo_path: str | None = None,
    status: str | None = None,
    profile: str | None = None,
    validation_state: str | None = None,
    archived: bool | None = None,
    limit: int = 50,
) -> dict:
    return search_session_history(
        query=query,
        repo_path=repo_path,
        status=status,
        profile=profile,
        validation_state=validation_state,
        archived=archived,
        limit=limit,
    )


@app.get("/api/history/analytics")
def history_analytics() -> dict:
    return session_analytics()


@app.get("/api/history/compare")
def history_compare(repo_path: str) -> dict:
    return compare_repo_sessions(repo_path)


@app.get("/api/history/views")
def history_views() -> dict:
    return list_history_views()


@app.post("/api/history/views")
def history_view_save(request: HistoryViewWriteRequest) -> dict:
    try:
        return save_history_view(
            view_id=request.view_id,
            label=request.label,
            description=request.description,
            filters=request.filters,
        )
    except HistoryViewError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/history/views/delete")
def history_view_delete(request: HistoryViewDeleteRequest) -> dict:
    try:
        return delete_history_view(request.view_id)
    except HistoryViewError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/automation/queue")
def global_automation_queue(
    min_priority: int = 0,
    executable_only: bool = False,
    include_archived: bool = True,
    limit: int = 50,
) -> dict:
    return automation_queue(
        min_priority=min_priority,
        executable_only=executable_only,
        include_archived=include_archived,
        limit=limit,
    )


@app.post("/api/automation/execute-next")
def global_automation_execute_next(request: AutomationExecuteNextRequest) -> dict:
    try:
        return execute_next_automation(
            min_priority=request.min_priority,
            launch=request.launch,
            include_archived=request.include_archived,
        )
    except SessionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/automation/sweep")
def global_automation_sweep(request: AutomationSweepRequest) -> dict:
    try:
        return sweep_automation(
            min_priority=request.min_priority,
            max_actions=request.max_actions,
            launch=request.launch,
            include_archived=request.include_archived,
        )
    except SessionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/codex/history")
def codex_history(query: str | None = None, cwd: str | None = None, limit: int = 20) -> dict:
    client = get_runner_client()
    return {"threads": client.list_codex_threads(cwd, query, limit=limit)}


@app.get("/api/codex/imported-history")
def codex_imported_history(query: str | None = None, cwd: str | None = None, limit: int = 20) -> dict:
    client = get_runner_client()
    return {"threads": client.list_imported_codex_sessions(cwd, query, limit=limit)}


@app.get("/api/validation-presets")
def validation_presets() -> dict:
    return {"presets": list_manager_validation_presets()}


@app.get("/api/codex-config-presets")
def codex_config_presets(repo_path: str | None = None) -> dict:
    return {"presets": list_manager_codex_config_presets(repo_path)}


@app.get("/api/codex-config-presets/saved")
def saved_codex_config_presets(scope: str, repo_path: str | None = None) -> dict:
    try:
        return list_saved_codex_config_presets(scope, repo_path)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/codex-config-presets/saved")
def save_saved_codex_config_preset(request: CodexConfigPresetWriteRequest) -> dict:
    try:
        return save_codex_config_preset(
            scope=request.scope,
            preset_id=request.preset_id,
            label=request.label,
            description=request.description,
            content=request.content,
            mode=request.mode,
            repo_path=request.repo_path,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/codex-config-presets/saved/delete")
def delete_saved_codex_config_preset(request: CodexConfigPresetDeleteRequest) -> dict:
    try:
        return delete_codex_config_preset(
            scope=request.scope,
            preset_id=request.preset_id,
            repo_path=request.repo_path,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/repo-policies")
def repo_policies() -> dict:
    return {"policies": list_repo_policies()}


@app.get("/api/manager-rules")
def manager_rules() -> dict:
    try:
        return read_manager_rules()
    except ManagerRulesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/manager-rules")
def save_manager_rules(request: ManagerRulesWriteRequest) -> dict:
    try:
        return write_manager_rules(content=request.content)
    except ManagerRulesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/manager-rules/restore")
def restore_manager_rules_api(request: ManagerRulesRestoreRequest) -> dict:
    try:
        return restore_manager_rules(backup_path=request.backup_path)
    except ManagerRulesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/manager-rules/effective-session-defaults")
def manager_rule_session_defaults(repo_path: str | None = None, preset_id: str | None = None) -> dict:
    try:
        return effective_session_defaults(repo_path=repo_path, preset_id=preset_id)
    except ManagerRulesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/manager-rules/matches")
def manager_rule_matches(repo_path: str | None = None, preset_id: str | None = None) -> dict:
    try:
        return preview_manager_rule_matches(repo_path=repo_path, preset_id=preset_id)
    except ManagerRulesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/codex-environment")
def codex_environment(repo_path: str | None = None) -> dict:
    client = get_runner_client()
    try:
        return client.inspect_codex_environment(repo_path)
    except RunnerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/codex-skills")
def create_skill(request: CodexSkillCreateRequest) -> dict:
    client = get_runner_client()
    try:
        return client.create_codex_skill(
            scope=request.scope,
            name=request.name,
            summary=request.summary,
            repo_path=request.repo_path,
        )
    except RunnerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/codex-skill")
def codex_skill(scope: str, name: str, repo_path: str | None = None) -> dict:
    client = get_runner_client()
    try:
        return client.read_codex_skill(scope, name, repo_path)
    except RunnerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/codex-skill")
def save_codex_skill(request: CodexSkillWriteRequest) -> dict:
    client = get_runner_client()
    try:
        return client.write_codex_skill(request.scope, request.name, request.content, request.repo_path)
    except RunnerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/codex-skill/restore")
def restore_codex_skill_api(request: CodexSkillRestoreRequest) -> dict:
    client = get_runner_client()
    try:
        return client.restore_codex_skill(request.scope, request.name, request.backup_path, request.repo_path)
    except RunnerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/codex-skill/delete")
def delete_codex_skill_api(request: CodexSkillDeleteRequest) -> dict:
    client = get_runner_client()
    try:
        return client.delete_codex_skill(request.scope, request.name, request.repo_path)
    except RunnerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/codex-skills/catalog")
def codex_skill_catalog(request: CodexSkillCatalogListRequest) -> dict:
    client = get_runner_client()
    try:
        return client.list_installable_codex_skills(
            request.scope,
            request.repo_path,
            request.repo,
            request.path,
            request.ref,
        )
    except RunnerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/codex-skills/install/catalog")
def install_codex_skill_catalog(request: CodexSkillCatalogInstallRequest) -> dict:
    client = get_runner_client()
    try:
        return client.install_codex_skill_from_catalog(
            request.scope,
            request.name,
            request.repo_path,
            request.repo,
            request.path,
            request.ref,
            request.method,
        )
    except RunnerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/codex-skills/install/github")
def install_codex_skill_github(request: CodexSkillGithubInstallRequest) -> dict:
    client = get_runner_client()
    try:
        return client.install_codex_skill_from_github(
            request.scope,
            request.repo_path,
            request.github_repo,
            request.github_url,
            request.github_path,
            request.ref,
            request.method,
            request.name,
        )
    except RunnerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/codex-prompts")
def codex_prompts(scope: str, repo_path: str | None = None) -> dict:
    client = get_runner_client()
    try:
        return {"prompts": client.list_codex_prompts(scope, repo_path)}
    except RunnerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/codex-prompts")
def create_codex_prompt_api(request: CodexPromptWriteRequest) -> dict:
    client = get_runner_client()
    try:
        return client.create_codex_prompt(request.scope, request.name, request.content, request.repo_path)
    except RunnerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/codex-prompt")
def codex_prompt(scope: str, name: str, repo_path: str | None = None) -> dict:
    client = get_runner_client()
    try:
        return client.read_codex_prompt(scope, name, repo_path)
    except RunnerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/codex-prompt")
def save_codex_prompt(request: CodexPromptWriteRequest) -> dict:
    client = get_runner_client()
    try:
        return client.write_codex_prompt(request.scope, request.name, request.content, request.repo_path)
    except RunnerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/codex-prompt/restore")
def restore_codex_prompt_api(request: CodexPromptRestoreRequest) -> dict:
    client = get_runner_client()
    try:
        return client.restore_codex_prompt(request.scope, request.name, request.backup_path, request.repo_path)
    except RunnerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/codex-prompt/delete")
def delete_codex_prompt_api(request: CodexPromptDeleteRequest) -> dict:
    client = get_runner_client()
    try:
        return client.delete_codex_prompt(request.scope, request.name, request.repo_path)
    except RunnerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/codex-config")
def codex_config(scope: str, repo_path: str | None = None) -> dict:
    client = get_runner_client()
    try:
        return client.read_codex_config(scope, repo_path)
    except RunnerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/codex-config/preview")
def preview_codex_config_api(request: CodexConfigWriteRequest) -> dict:
    client = get_runner_client()
    try:
        return client.preview_codex_config(request.scope, request.content, request.repo_path)
    except RunnerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/codex-config")
def save_codex_config(request: CodexConfigWriteRequest) -> dict:
    client = get_runner_client()
    try:
        return client.write_codex_config(request.scope, request.content, request.repo_path)
    except RunnerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/codex-config/structured")
def save_structured_codex_config(request: CodexConfigStructuredWriteRequest) -> dict:
    client = get_runner_client()
    try:
        return client.write_structured_codex_config(
            request.scope,
            request.scalar_fields,
            request.advanced_json,
            request.repo_path,
        )
    except RunnerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/codex-config/restore")
def restore_codex_config_api(request: CodexConfigRestoreRequest) -> dict:
    client = get_runner_client()
    try:
        return client.restore_codex_config(request.scope, request.backup_path, request.repo_path)
    except RunnerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/codex-rules")
def codex_rules(scope: str, repo_path: str | None = None) -> dict:
    client = get_runner_client()
    try:
        return client.read_codex_rules(scope, repo_path)
    except RunnerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/codex-rules")
def save_codex_rules(request: CodexRulesWriteRequest) -> dict:
    client = get_runner_client()
    try:
        return client.write_codex_rules(request.scope, request.content, request.repo_path)
    except RunnerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/codex-rules/restore")
def restore_codex_rules_api(request: CodexRulesRestoreRequest) -> dict:
    client = get_runner_client()
    try:
        return client.restore_codex_rules(request.scope, request.backup_path, request.repo_path)
    except RunnerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/codex-agents")
def codex_agents() -> dict:
    client = get_runner_client()
    try:
        return {"agents": client.list_codex_agents()}
    except RunnerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/codex-agents")
def create_codex_agent_api(request: CodexAgentCreateRequest) -> dict:
    client = get_runner_client()
    try:
        return client.create_codex_agent(request.name, request.summary)
    except RunnerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/codex-agent-config")
def codex_agent_config(name: str) -> dict:
    client = get_runner_client()
    try:
        return client.read_codex_agent_config(name)
    except RunnerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/codex-agent-config")
def save_codex_agent_config(request: CodexAgentConfigWriteRequest) -> dict:
    client = get_runner_client()
    try:
        return client.write_codex_agent_config(request.name, request.content)
    except RunnerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/codex-agent-config/restore")
def restore_codex_agent_config_api(request: CodexAgentConfigRestoreRequest) -> dict:
    client = get_runner_client()
    try:
        return client.restore_codex_agent_config(request.name, request.backup_path)
    except RunnerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/codex-mcp")
def codex_mcp(scope: str, repo_path: str | None = None) -> dict:
    client = get_runner_client()
    try:
        return client.list_codex_mcp_servers(scope, repo_path)
    except RunnerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/codex-mcp/dependencies")
def codex_mcp_dependencies(scope: str, name: str, repo_path: str | None = None) -> dict:
    try:
        return describe_codex_mcp_dependencies(scope=scope, name=name, repo_path=repo_path)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/codex-mcp")
def create_codex_mcp_api(request: CodexMcpCreateRequest) -> dict:
    client = get_runner_client()
    try:
        return client.create_codex_mcp_server(
            request.scope,
            request.name,
            request.command,
            request.args,
            request.cwd,
            request.env,
            request.repo_path,
        )
    except RunnerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/codex-mcp/delete")
def delete_codex_mcp_api(request: CodexMcpDeleteRequest) -> dict:
    client = get_runner_client()
    try:
        return client.delete_codex_mcp_server(request.scope, request.name, request.repo_path)
    except RunnerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/codex-mcp/update")
def update_codex_mcp_api(request: CodexMcpCreateRequest) -> dict:
    client = get_runner_client()
    try:
        return client.update_codex_mcp_server(
            request.scope,
            request.name,
            request.command,
            request.args,
            request.cwd,
            request.env,
            request.repo_path,
        )
    except RunnerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/codex-mcp/enabled")
def set_codex_mcp_enabled_api(request: CodexMcpEnabledRequest) -> dict:
    client = get_runner_client()
    try:
        return client.set_codex_mcp_server_enabled(request.scope, request.name, request.enabled, request.repo_path)
    except RunnerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/validation-presets/apply")
def apply_validation_preset(request: ValidationPresetApplyRequest) -> dict:
    client = get_runner_client()
    config_path = client.apply_validation_preset(request.repo_path, request.preset_id)
    return {"configPath": config_path}


@app.post("/api/codex-config-presets/preview")
def preview_codex_config_preset_apply(request: CodexConfigPresetApplyRequest) -> dict:
    try:
        return preview_apply_codex_config_preset(
            scope=request.scope,
            preset_id=request.preset_id,
            repo_path=request.repo_path,
            mode=request.mode,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/codex-config-presets/apply")
def apply_codex_config_preset(request: CodexConfigPresetApplyRequest) -> dict:
    try:
        return apply_codex_config_preset_payload(
            scope=request.scope,
            preset_id=request.preset_id,
            repo_path=request.repo_path,
            mode=request.mode,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/validation-recipes/materialize")
def materialize_validation_recipe(request: ValidationRecipeMaterializeRequest) -> dict:
    client = get_runner_client()
    config_path = client.materialize_validation_recipe(request.repo_path, request.recipe_json)
    return {"configPath": config_path}


@app.get("/api/codex/resume-points")
def codex_resume_points(
    thread_id: str | None = None,
    cwd: str | None = None,
    prompt: str | None = None,
    limit: int = 12,
) -> dict:
    client = get_runner_client()
    threads = client.list_resume_candidates(thread_id, cwd, prompt, limit=limit)
    return {"threads": threads}


@app.get("/api/sessions/{session_id}/resume-points")
def session_resume_points(session_id: str, limit: int = 12) -> dict:
    session = _session_or_404(session_id)
    client = get_runner_client()
    threads = client.list_resume_candidates(
        session.codex_session_id,
        session.cwd,
        session.prompt,
        limit=limit,
    )
    return {"threads": threads}


@app.post("/api/sessions/start")
def session_start(request: StartRequest) -> dict:
    try:
        session = create_managed_session(
            name=request.name,
            repo_path=request.repo_path,
            profile=request.profile,
            prompt=request.prompt,
            approval_policy=request.approval_policy,
            create_worktree_for_writes=request.create_worktree_for_writes,
            auto_init_git=request.auto_init_git,
            require_changelog=request.require_changelog,
            launch=request.launch,
            manager_defaults_fields=request.manager_defaults_fields,
            defer_launch=True,
        )
    except SessionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return asdict(session)


@app.post("/api/sessions/{session_id}/open")
def session_open(session_id: str) -> dict:
    try:
        command = open_session(session_id)
    except SessionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"command": command}


@app.post("/api/sessions/{session_id}/stop")
def session_stop(session_id: str) -> dict:
    try:
        session = stop_session(session_id)
    except SessionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        create_handoff(session.id, kind="stop")
    except SessionError:
        pass
    return asdict(session)


@app.delete("/api/sessions/{session_id}")
def session_delete(session_id: str) -> dict:
    try:
        name = delete_session(session_id)
    except SessionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"deleted": name}


@app.post("/api/sessions/bulk-delete/stopped")
def session_bulk_delete_stopped() -> dict:
    try:
        names = delete_stopped_sessions()
    except SessionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"deleted": names, "count": len(names)}


@app.post("/api/sessions/bulk-delete/test-named")
def session_bulk_delete_test_named() -> dict:
    try:
        names = delete_test_named_sessions()
    except SessionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"deleted": names, "count": len(names)}


@app.post("/api/sessions/{session_id}/resume")
def session_resume(session_id: str) -> dict:
    try:
        session, command = resume_session(session_id)
    except SessionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"session": asdict(session), "command": command}


@app.post("/api/sessions/{session_id}/codex-session-link")
def session_codex_session_link(session_id: str, request: CodexSessionLinkRequest) -> dict:
    try:
        session = set_codex_session_id(
            session_id,
            request.codex_session_id,
            codex_rollout_path=request.codex_rollout_path,
            codex_updated_at=request.codex_updated_at,
        )
    except SessionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return asdict(session)


@app.post("/api/sessions/adopt")
def session_adopt(request: AdoptRequest) -> dict:
    try:
        session = adopt_session(
            name=request.name,
            codex_session_id=request.codex_session_id,
            repo_path=request.repo_path,
            profile=request.profile,
        )
    except SessionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return asdict(session)


def _resolve_frontend_dist() -> Path | None:
    explicit = os.environ.get("CODEXMGR_FRONTEND_DIST")
    if explicit:
        p = Path(explicit).expanduser().resolve()
        if p.exists():
            return p

    candidates = [
        Path("/app/frontend/dist"),
        Path(__file__).resolve().parents[3] / "frontend" / "dist",
        Path.cwd() / "frontend" / "dist",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


frontend_dist = _resolve_frontend_dist()
if frontend_dist is not None:
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")

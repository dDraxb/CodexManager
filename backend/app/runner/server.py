from __future__ import annotations

import os

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from app.runner.client import LocalRunnerClient
from app.runner.contracts import RunnerError


class RepoPathRequest(BaseModel):
    repo_path: str | None = None


class EnsureGitRepoRequest(BaseModel):
    repo_path: str
    auto_init: bool = False


class CreateWorktreeRequest(BaseModel):
    repo_path: str
    session_name: str
    branch: str
    auto_init: bool = False


class ChangedFilesRequest(BaseModel):
    repo_path: str
    cwd: str | None = None


class BranchRequest(BaseModel):
    repo_path: str
    cwd: str | None = None


class ChangelogRequest(BaseModel):
    repo_path: str
    session_name: str
    prompt: str | None = None
    timestamp: str


class FindRecentCodexSessionRequest(BaseModel):
    cwd: str
    prompt: str | None = None
    since: str | None = None


class CodexThreadListRequest(BaseModel):
    cwd: str | None = None
    query: str | None = None
    limit: int = 20


class ResumeCandidateRequest(BaseModel):
    thread_id: str | None = None
    cwd: str | None = None
    prompt: str | None = None
    limit: int = 12


class BuildCodexLaunchRequest(BaseModel):
    profile: str
    prompt: str | None = None


class ValidationPresetApplyRequest(BaseModel):
    repo_path: str
    preset_id: str


class ValidationRecipeMaterializeRequest(BaseModel):
    repo_path: str
    recipe_json: str


class CodexSkillCreateRequest(BaseModel):
    scope: str
    name: str
    summary: str = ""
    repo_path: str | None = None


class CodexConfigReadRequest(BaseModel):
    scope: str
    repo_path: str | None = None


class CodexConfigWriteRequest(BaseModel):
    scope: str
    content: str
    repo_path: str | None = None


class CodexConfigRestoreRequest(BaseModel):
    scope: str
    backup_path: str
    repo_path: str | None = None


class CodexRulesReadRequest(BaseModel):
    scope: str
    repo_path: str | None = None


class CodexRulesWriteRequest(BaseModel):
    scope: str
    content: str
    repo_path: str | None = None


class CodexRulesRestoreRequest(BaseModel):
    scope: str
    backup_path: str
    repo_path: str | None = None


class CodexAgentCreateRequest(BaseModel):
    name: str
    summary: str = ""


class CodexMcpListRequest(BaseModel):
    scope: str
    repo_path: str | None = None


class CodexMcpCreateRequest(BaseModel):
    scope: str
    name: str
    command: str
    args: list[str] = []
    cwd: str | None = None
    env: dict[str, str] = {}
    repo_path: str | None = None


class CodexMcpDeleteRequest(BaseModel):
    scope: str
    name: str
    repo_path: str | None = None


class TmuxSessionRequest(BaseModel):
    session_name: str


class TmuxCapturePaneRequest(BaseModel):
    session_name: str
    tail: int = 200


class TmuxCreateSessionRequest(BaseModel):
    session_name: str
    cwd: str
    log_path: str
    launch_cmd: str | None = None


def create_app(*, api_key: str | None = None) -> FastAPI:
    app = FastAPI(title="codex-runner")
    runner = LocalRunnerClient()
    expected_api_key = api_key if api_key is not None else (
        os.environ.get("RUNNER_API_KEY") or os.environ.get("CODEXMGR_RUNNER_API_KEY")
    )

    def require_auth(provided_api_key: str | None) -> None:
        if expected_api_key and provided_api_key != expected_api_key:
            raise HTTPException(status_code=401, detail="invalid runner api key")

    def runner_call(fn):
        try:
            return fn()
        except RunnerError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    @app.post("/resolve-repo-path")
    def resolve_repo_path(request: RepoPathRequest, x_runner_api_key: str | None = Header(default=None)) -> dict:
        require_auth(x_runner_api_key)
        repo_path = runner_call(lambda: runner.resolve_repo_path(request.repo_path))
        return {"repo_path": repo_path}

    @app.post("/build-codex-launch-command")
    def build_codex_launch_command(
        request: BuildCodexLaunchRequest,
        x_runner_api_key: str | None = Header(default=None),
    ) -> dict:
        require_auth(x_runner_api_key)
        launch_command = runner_call(lambda: runner.build_codex_launch_command(request.profile, request.prompt))
        return {"launch_command": launch_command}

    @app.post("/ensure-git-repo")
    def ensure_repo(request: EnsureGitRepoRequest, x_runner_api_key: str | None = Header(default=None)) -> dict:
        require_auth(x_runner_api_key)
        runner_call(lambda: runner.ensure_git_repo(request.repo_path, auto_init=request.auto_init))
        return {"ok": True}

    @app.post("/create-worktree")
    def create_worktree_endpoint(
        request: CreateWorktreeRequest,
        x_runner_api_key: str | None = Header(default=None),
    ) -> dict:
        require_auth(x_runner_api_key)
        worktree_path = runner_call(
            lambda: runner.create_worktree(
                request.repo_path,
                request.session_name,
                request.branch,
                auto_init=request.auto_init,
            )
        )
        return {"worktree_path": worktree_path}

    @app.post("/changed-files")
    def changed_files_endpoint(
        request: ChangedFilesRequest,
        x_runner_api_key: str | None = Header(default=None),
    ) -> dict:
        require_auth(x_runner_api_key)
        files = runner_call(lambda: runner.changed_files(request.repo_path, request.cwd))
        return {"files": files}

    @app.post("/current-branch")
    def current_branch_endpoint(
        request: BranchRequest,
        x_runner_api_key: str | None = Header(default=None),
    ) -> dict:
        require_auth(x_runner_api_key)
        branch = runner_call(lambda: runner.current_branch(request.repo_path, request.cwd))
        return {"branch": branch}

    @app.post("/ensure-changelog-entry")
    def ensure_changelog_entry(
        request: ChangelogRequest,
        x_runner_api_key: str | None = Header(default=None),
    ) -> dict:
        require_auth(x_runner_api_key)
        changelog_path = runner_call(
            lambda: runner.ensure_changelog_entry(
                request.repo_path,
                request.session_name,
                request.prompt,
                request.timestamp,
            )
        )
        return {"changelog_path": changelog_path}

    @app.post("/detect-validation-recipe")
    def detect_validation_recipe_endpoint(
        request: RepoPathRequest,
        x_runner_api_key: str | None = Header(default=None),
    ) -> dict:
        require_auth(x_runner_api_key)
        recipe = runner_call(lambda: runner.detect_validation_recipe(request.repo_path or ""))
        return {"recipe": recipe}

    @app.post("/apply-validation-preset")
    def apply_validation_preset_endpoint(
        request: ValidationPresetApplyRequest,
        x_runner_api_key: str | None = Header(default=None),
    ) -> dict:
        require_auth(x_runner_api_key)
        config_path = runner_call(lambda: runner.apply_validation_preset(request.repo_path, request.preset_id))
        return {"config_path": config_path}

    @app.post("/materialize-validation-recipe")
    def materialize_validation_recipe_endpoint(
        request: ValidationRecipeMaterializeRequest,
        x_runner_api_key: str | None = Header(default=None),
    ) -> dict:
        require_auth(x_runner_api_key)
        config_path = runner_call(lambda: runner.materialize_validation_recipe(request.repo_path, request.recipe_json))
        return {"config_path": config_path}

    @app.post("/inspect-codex-environment")
    def inspect_codex_environment_endpoint(
        request: RepoPathRequest,
        x_runner_api_key: str | None = Header(default=None),
    ) -> dict:
        require_auth(x_runner_api_key)
        return runner_call(lambda: runner.inspect_codex_environment(request.repo_path))

    @app.post("/create-codex-skill")
    def create_codex_skill_endpoint(
        request: CodexSkillCreateRequest,
        x_runner_api_key: str | None = Header(default=None),
    ) -> dict:
        require_auth(x_runner_api_key)
        return runner_call(
            lambda: runner.create_codex_skill(
                request.scope,
                request.name,
                request.summary,
                request.repo_path,
            )
        )

    @app.post("/read-codex-config")
    def read_codex_config_endpoint(
        request: CodexConfigReadRequest,
        x_runner_api_key: str | None = Header(default=None),
    ) -> dict:
        require_auth(x_runner_api_key)
        return runner_call(lambda: runner.read_codex_config(request.scope, request.repo_path))

    @app.post("/write-codex-config")
    def write_codex_config_endpoint(
        request: CodexConfigWriteRequest,
        x_runner_api_key: str | None = Header(default=None),
    ) -> dict:
        require_auth(x_runner_api_key)
        return runner_call(lambda: runner.write_codex_config(request.scope, request.content, request.repo_path))

    @app.post("/restore-codex-config")
    def restore_codex_config_endpoint(
        request: CodexConfigRestoreRequest,
        x_runner_api_key: str | None = Header(default=None),
    ) -> dict:
        require_auth(x_runner_api_key)
        return runner_call(lambda: runner.restore_codex_config(request.scope, request.backup_path, request.repo_path))

    @app.post("/read-codex-rules")
    def read_codex_rules_endpoint(
        request: CodexRulesReadRequest,
        x_runner_api_key: str | None = Header(default=None),
    ) -> dict:
        require_auth(x_runner_api_key)
        return runner_call(lambda: runner.read_codex_rules(request.scope, request.repo_path))

    @app.post("/write-codex-rules")
    def write_codex_rules_endpoint(
        request: CodexRulesWriteRequest,
        x_runner_api_key: str | None = Header(default=None),
    ) -> dict:
        require_auth(x_runner_api_key)
        return runner_call(lambda: runner.write_codex_rules(request.scope, request.content, request.repo_path))

    @app.post("/restore-codex-rules")
    def restore_codex_rules_endpoint(
        request: CodexRulesRestoreRequest,
        x_runner_api_key: str | None = Header(default=None),
    ) -> dict:
        require_auth(x_runner_api_key)
        return runner_call(lambda: runner.restore_codex_rules(request.scope, request.backup_path, request.repo_path))

    @app.post("/list-codex-agents")
    def list_codex_agents_endpoint(x_runner_api_key: str | None = Header(default=None)) -> dict:
        require_auth(x_runner_api_key)
        return {"agents": runner_call(runner.list_codex_agents)}

    @app.post("/create-codex-agent")
    def create_codex_agent_endpoint(
        request: CodexAgentCreateRequest,
        x_runner_api_key: str | None = Header(default=None),
    ) -> dict:
        require_auth(x_runner_api_key)
        return runner_call(lambda: runner.create_codex_agent(request.name, request.summary))

    @app.post("/list-codex-mcp-servers")
    def list_codex_mcp_servers_endpoint(
        request: CodexMcpListRequest,
        x_runner_api_key: str | None = Header(default=None),
    ) -> dict:
        require_auth(x_runner_api_key)
        return runner_call(lambda: runner.list_codex_mcp_servers(request.scope, request.repo_path))

    @app.post("/create-codex-mcp-server")
    def create_codex_mcp_server_endpoint(
        request: CodexMcpCreateRequest,
        x_runner_api_key: str | None = Header(default=None),
    ) -> dict:
        require_auth(x_runner_api_key)
        return runner_call(
            lambda: runner.create_codex_mcp_server(
                request.scope,
                request.name,
                request.command,
                request.args,
                request.cwd,
                request.env,
                request.repo_path,
            )
        )

    @app.post("/delete-codex-mcp-server")
    def delete_codex_mcp_server_endpoint(
        request: CodexMcpDeleteRequest,
        x_runner_api_key: str | None = Header(default=None),
    ) -> dict:
        require_auth(x_runner_api_key)
        return runner_call(lambda: runner.delete_codex_mcp_server(request.scope, request.name, request.repo_path))

    @app.post("/codex/find-recent-session")
    def find_recent_codex_session(
        request: FindRecentCodexSessionRequest,
        x_runner_api_key: str | None = Header(default=None),
    ) -> dict:
        require_auth(x_runner_api_key)
        codex_session_id = runner_call(
            lambda: runner.find_recent_codex_session(request.cwd, request.prompt, request.since)
        )
        return {"codex_session_id": codex_session_id}

    @app.post("/codex/list-threads")
    def codex_list_threads(
        request: CodexThreadListRequest,
        x_runner_api_key: str | None = Header(default=None),
    ) -> dict:
        require_auth(x_runner_api_key)
        threads = runner_call(lambda: runner.list_codex_threads(request.cwd, request.query, request.limit))
        return {"threads": threads}

    @app.post("/codex/list-resume-candidates")
    def codex_list_resume_candidates(
        request: ResumeCandidateRequest,
        x_runner_api_key: str | None = Header(default=None),
    ) -> dict:
        require_auth(x_runner_api_key)
        threads = runner_call(
            lambda: runner.list_resume_candidates(request.thread_id, request.cwd, request.prompt, request.limit)
        )
        return {"threads": threads}

    @app.post("/tmux/session-exists")
    def tmux_session_exists(
        request: TmuxSessionRequest,
        x_runner_api_key: str | None = Header(default=None),
    ) -> dict:
        require_auth(x_runner_api_key)
        exists = runner_call(lambda: runner.session_exists(request.session_name))
        return {"exists": exists}

    @app.post("/tmux/create-session")
    def tmux_create_session(
        request: TmuxCreateSessionRequest,
        x_runner_api_key: str | None = Header(default=None),
    ) -> dict:
        require_auth(x_runner_api_key)
        runner_call(
            lambda: runner.create_session(
                request.session_name,
                request.cwd,
                request.log_path,
                request.launch_cmd,
            )
        )
        return {"ok": True}

    @app.post("/tmux/stop-session")
    def tmux_stop_session(request: TmuxSessionRequest, x_runner_api_key: str | None = Header(default=None)) -> dict:
        require_auth(x_runner_api_key)
        runner_call(lambda: runner.stop_session(request.session_name))
        return {"ok": True}

    @app.post("/tmux/attach-command")
    def tmux_attach_command(
        request: TmuxSessionRequest,
        x_runner_api_key: str | None = Header(default=None),
    ) -> dict:
        require_auth(x_runner_api_key)
        command = runner_call(lambda: runner.attach_command(request.session_name))
        return {"command": command}

    @app.post("/tmux/pane-pid")
    def tmux_pane_pid(request: TmuxSessionRequest, x_runner_api_key: str | None = Header(default=None)) -> dict:
        require_auth(x_runner_api_key)
        pane_pid = runner_call(lambda: runner.pane_pid(request.session_name))
        return {"pane_pid": pane_pid}

    @app.post("/tmux/capture-pane")
    def tmux_capture_pane(
        request: TmuxCapturePaneRequest,
        x_runner_api_key: str | None = Header(default=None),
    ) -> dict:
        require_auth(x_runner_api_key)
        lines = runner_call(lambda: runner.capture_pane(request.session_name, request.tail))
        return {"lines": lines}

    @app.post("/tmux/is-attached")
    def tmux_is_attached(request: TmuxSessionRequest, x_runner_api_key: str | None = Header(default=None)) -> dict:
        require_auth(x_runner_api_key)
        attached = runner_call(lambda: runner.is_session_attached(request.session_name))
        return {"attached": attached}

    return app


app = create_app()

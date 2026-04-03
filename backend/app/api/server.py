from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.monitoring.reconciler import reconcile_once
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

app = FastAPI(title="codex-session-manager")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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


class AdoptRequest(BaseModel):
    name: str
    codex_session_id: str = Field(alias="codexSessionId")
    repo_path: str = Field(alias="repoPath")
    profile: str = "read-only"


class CodexSessionLinkRequest(BaseModel):
    codex_session_id: str = Field(alias="codexSessionId")
    codex_rollout_path: str | None = Field(default=None, alias="codexRolloutPath")
    codex_updated_at: int | None = Field(default=None, alias="codexUpdatedAt")


def _session_or_404(session_id: str):
    session = get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return session


@app.get("/api/health")
def health() -> dict:
    touched = reconcile_once()
    return {"ok": True, "reconciled": touched}


@app.get("/api/summary")
def summary() -> dict:
    reconcile_once()
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
    return [asdict(s) for s in list_sessions()]


@app.get("/api/sessions/{session_id}")
def session_detail(session_id: str) -> dict:
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


@app.get("/api/codex/history")
def codex_history(query: str | None = None, cwd: str | None = None, limit: int = 20) -> dict:
    client = get_runner_client()
    return {"threads": client.list_codex_threads(cwd, query, limit=limit)}


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

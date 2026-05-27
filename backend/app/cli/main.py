from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import typer
import uvicorn

from app.api.server import app as api_app
from app.core.settings import load_settings
from app.monitoring.reconciler import reconcile_once
from app.runner.server import app as runner_app
from app.services.sessions import (
    SessionError,
    adopt_session,
    create_managed_session,
    delete_session,
    get_session,
    list_events,
    list_sessions,
    open_session,
    resume_session,
    stop_session,
)

app = typer.Typer(help="Codex Session Manager CLI")



def _print_session_table(rows: list[dict]) -> None:
    if not rows:
        typer.echo("No sessions found.")
        return

    headers = ["name", "status", "provider", "mode", "profile", "observability", "repo_path", "updated_at"]
    widths = {h: max(len(h), max(len(str(row.get(h, ""))) for row in rows)) for h in headers}

    typer.echo("  ".join(h.ljust(widths[h]) for h in headers))
    typer.echo("  ".join("-" * widths[h] for h in headers))
    for row in rows:
        typer.echo("  ".join(str(row.get(h, "")).ljust(widths[h]) for h in headers))


@app.command()
def start(
    name: str = typer.Option(..., help="Session name"),
    repo: Path | None = typer.Option(None, exists=True, file_okay=False, dir_okay=True, help="Working directory path"),
    provider: str = typer.Option("codex", help="Execution provider"),
    profile: str = typer.Option("safe-edit", help="Permission profile"),
    prompt: str | None = typer.Option(None, help="Task prompt"),
    approval_policy: str = typer.Option("on-request", help="Approval policy label"),
    create_worktree: bool = typer.Option(False, "--create-worktree/--no-create-worktree", help="Use dedicated worktree for writable profiles"),
    auto_init_git: bool = typer.Option(False, "--auto-init-git", help="Initialize git repo automatically when missing"),
    require_changelog: bool = typer.Option(False, "--require-changelog/--no-require-changelog", help="Append a CHANGELOG.md session entry before starting"),
    launch: bool = typer.Option(True, "--launch/--no-launch", help="Launch inside tmux"),
) -> None:
    """Create a managed session."""
    try:
        session = create_managed_session(
            name=name,
            repo_path=str(repo.expanduser().resolve()) if repo is not None else None,
            provider=provider,
            profile=profile,
            prompt=prompt,
            approval_policy=approval_policy,
            create_worktree_for_writes=create_worktree,
            auto_init_git=auto_init_git,
            require_changelog=require_changelog,
            launch=launch,
        )
    except SessionError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Created session: {session.name} ({session.id}) [{session.status}]")


@app.command("list")
def list_cmd(
    json_output: bool = typer.Option(False, "--json", help="Output JSON"),
    reconcile: bool = typer.Option(False, help="Run monitor reconciliation before listing"),
) -> None:
    """List known sessions."""
    if reconcile:
        reconcile_once()

    sessions = [asdict(s) for s in list_sessions()]
    if json_output:
        typer.echo(json.dumps(sessions, indent=2))
        return
    _print_session_table(sessions)


@app.command()
def inspect(name_or_id: str, tail_events: int = typer.Option(20, min=1, max=500)) -> None:
    """Inspect one session and recent events."""
    session = get_session(name_or_id)
    if session is None:
        typer.echo(f"session '{name_or_id}' not found", err=True)
        raise typer.Exit(code=1)

    payload = asdict(session)
    payload["events"] = [asdict(e) for e in list_events(session.id, limit=tail_events)]
    typer.echo(json.dumps(payload, indent=2))


@app.command()
def stop(name_or_id: str) -> None:
    """Stop a managed session."""
    try:
        session = stop_session(name_or_id)
    except SessionError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Stopped session: {session.name} ({session.id})")


@app.command("delete")
def delete_cmd(name_or_id: str) -> None:
    """Delete a session record and local logs."""
    try:
        name = delete_session(name_or_id)
    except SessionError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Deleted session: {name}")


@app.command()
def adopt(
    name: str = typer.Option(..., help="Local session name"),
    provider: str = typer.Option("codex", help="Execution provider"),
    codex_session: str = typer.Option(..., "--codex-session", help="Codex-native session id"),
    repo: Path = typer.Option(..., exists=True, file_okay=False, dir_okay=True, help="Repo path"),
    profile: str = typer.Option("read-only", help="Permission profile"),
) -> None:
    """Adopt an existing Codex session id."""
    try:
        session = adopt_session(
            name=name,
            provider=provider,
            codex_session_id=codex_session,
            repo_path=str(repo.expanduser().resolve()),
            profile=profile,
        )
    except SessionError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Adopted session: {session.name} ({session.id})")


@app.command()
def open(name_or_id: str) -> None:
    """Print tmux attach command for a running session."""
    try:
        command = open_session(name_or_id)
    except SessionError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(command)


@app.command()
def resume(name_or_id: str) -> None:
    """Resume/reopen a session."""
    try:
        session, command = resume_session(name_or_id)
    except SessionError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Resumed session: {session.name} ({session.id})")
    typer.echo(command)


@app.command()
def ui(host: str | None = typer.Option(None), port: int | None = typer.Option(None)) -> None:
    """Start local API/UI server."""
    settings = load_settings()
    resolved_host = host or settings.ui_host
    resolved_port = port or settings.ui_port
    typer.echo(f"Serving dashboard on http://{resolved_host}:{resolved_port}")
    uvicorn.run(api_app, host=resolved_host, port=resolved_port, log_level="info")


@app.command()
def runner(
    host: str = typer.Option("127.0.0.1", help="Runner bind host"),
    port: int = typer.Option(8788, help="Runner bind port"),
) -> None:
    """Start the execution runner API on the host."""
    typer.echo(f"Serving runner on http://{host}:{port}")
    uvicorn.run(runner_app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    app()

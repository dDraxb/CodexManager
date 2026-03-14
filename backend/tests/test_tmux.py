from __future__ import annotations


def test_create_session_preserves_tty_and_uses_pipe_pane(monkeypatch):
    from app.services import tmux

    calls: list[list[str]] = []

    monkeypatch.setattr(tmux, "command_exists", lambda name: True)
    monkeypatch.setattr(tmux, "session_exists", lambda session_name: False)
    monkeypatch.setattr(tmux, "run", lambda cmd: calls.append(cmd))

    tmux.create_session("codex-demo", "/tmp/repo", "/tmp/output.log", "codex -s workspace-write")

    assert calls == [
        ["tmux", "new-session", "-d", "-s", "codex-demo", "-c", "/tmp/repo", "codex -s workspace-write"],
        ["tmux", "pipe-pane", "-o", "-t", "codex-demo", "cat >> /tmp/output.log"],
    ]


def test_capture_pane_reads_rendered_lines(monkeypatch):
    from app.services import tmux

    calls: list[list[str]] = []

    class Result:
        stdout = "line one\nline two\n"

    monkeypatch.setattr(tmux, "command_exists", lambda name: True)
    monkeypatch.setattr(tmux, "session_exists", lambda session_name: True)

    def fake_run(cmd):
        calls.append(cmd)
        return Result()

    monkeypatch.setattr(tmux, "run", fake_run)

    lines = tmux.capture_pane("codex-demo", tail=50)

    assert lines == ["line one", "line two"]
    assert calls == [["tmux", "capture-pane", "-p", "-t", "codex-demo", "-S", "-50"]]


def test_is_session_attached_reads_tmux_flag(monkeypatch):
    from app.services import tmux

    class Result:
        stdout = "1\n"

    monkeypatch.setattr(tmux, "command_exists", lambda name: True)
    monkeypatch.setattr(tmux, "session_exists", lambda session_name: True)
    monkeypatch.setattr(tmux, "run", lambda cmd: Result())

    assert tmux.is_session_attached("codex-demo") is True

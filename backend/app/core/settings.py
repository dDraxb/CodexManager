from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    app_home: Path
    db_path: Path
    sessions_dir: Path
    worktrees_dir: Path
    ui_host: str
    ui_port: int
    monitor_idle_seconds: int



def load_settings() -> Settings:
    app_home = Path(os.environ.get("CODEXMGR_HOME", str(Path.home() / ".codexmgr"))).expanduser()
    return Settings(
        app_home=app_home,
        db_path=app_home / "codexmgr.db",
        sessions_dir=app_home / "sessions",
        worktrees_dir=app_home / "worktrees",
        ui_host=os.environ.get("CODEXMGR_UI_HOST", "127.0.0.1"),
        ui_port=int(os.environ.get("CODEXMGR_UI_PORT", "8790")),
        monitor_idle_seconds=int(os.environ.get("CODEXMGR_IDLE_SECONDS", "300")),
    )

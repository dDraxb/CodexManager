from __future__ import annotations

import subprocess
from pathlib import Path


class ShellError(RuntimeError):
    pass


def run(cmd: list[str], cwd: str | Path | None = None) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise ShellError(f"command failed ({proc.returncode}): {' '.join(cmd)}\n{proc.stderr.strip()}")
    return proc


def command_exists(name: str) -> bool:
    proc = subprocess.run(["which", name], text=True, capture_output=True, check=False)
    return proc.returncode == 0

from __future__ import annotations

from datetime import datetime
from pathlib import Path


def _backup_dir(path: Path) -> Path:
    return path.parent / ".codexmgr-backups"


def backup_file(path: Path) -> str | None:
    if not path.exists():
        return None
    backup_dir = _backup_dir(path)
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup_path = backup_dir / f"{path.name}.{timestamp}.bak"
    backup_path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return str(backup_path)


def list_backups(path: Path) -> list[dict]:
    backup_dir = _backup_dir(path)
    if not backup_dir.exists() or not backup_dir.is_dir():
        return []
    backups: list[dict] = []
    prefix = f"{path.name}."
    suffix = ".bak"
    for child in sorted(backup_dir.iterdir(), key=lambda item: item.name, reverse=True):
        if not child.is_file():
            continue
        if not child.name.startswith(prefix) or not child.name.endswith(suffix):
            continue
        backups.append(
            {
                "path": str(child),
                "name": child.name,
                "modifiedAt": datetime.fromtimestamp(child.stat().st_mtime).isoformat(),
            }
        )
    return backups


def restore_backup(path: Path, backup_path: str) -> dict:
    source = Path(backup_path).expanduser()
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"backup not found: {backup_path}")
    current_backup = backup_file(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return {
        "path": str(path),
        "restoredFrom": str(source),
        "backupPath": current_backup,
    }

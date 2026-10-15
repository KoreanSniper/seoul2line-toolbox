from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys


def application_root() -> Path:
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]


def data_directory() -> Path:
    if getattr(sys, "frozen", False):
        local = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
        return local / "seoul2line Toolbox" / "user_data"
    return application_root() / "user_data"


def migrate_legacy_data(destination: Path) -> None:
    """Copy old installed data once; never remove or replace the user's files."""
    if not getattr(sys, "frozen", False) or (destination / ".legacy-migration-complete").exists():
        return
    roots = [application_root() / "user_data", Path(getattr(sys, "_MEIPASS", application_root())) / "user_data"]
    destination.mkdir(parents=True, exist_ok=True)
    pending: dict[Path, Path] = {}
    for source in roots:
        if not source.is_dir() or source.resolve() == destination.resolve():
            continue
        for path in source.rglob("*"):
            if path.is_symlink() or not path.is_file() or source.resolve() not in path.resolve().parents:
                continue
            relative = path.relative_to(source)
            previous = pending.get(relative)
            if previous is None or path.stat().st_mtime_ns > previous.stat().st_mtime_ns:
                pending[relative] = path
    for relative, path in pending.items():
        target = destination / relative
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    (destination / ".legacy-migration-complete").touch()

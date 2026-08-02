from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from types import ModuleType

from ..config import app_data_dir

try:
    import winreg
except ImportError:  # pragma: no cover - Windows-only standard library module
    winreg = None

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "PourNotify"
LEGACY_NAMES = ("PourNotify.lnk", "PourNotify.exe")


def startup_supported() -> bool:
    return sys.platform == "win32" and winreg is not None


def _quoted(value: str) -> str:
    if '"' in value:
        raise ValueError("Executable paths containing quotes are not supported.")
    return f'"{value}"'


def startup_command(executable: Path | None = None) -> str:
    target = Path(executable or sys.executable).resolve()
    if executable is not None or getattr(sys, "frozen", False):
        return f"{_quoted(str(target))} --background"
    return f"{_quoted(str(target))} -m pournotify --background"


def legacy_startup_entries(startup_dir: Path | None = None) -> list[Path]:
    if startup_dir is None:
        roaming = os.environ.get("APPDATA")
        if not roaming:
            return []
        startup_dir = (
            Path(roaming) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        )
    return [startup_dir / name for name in LEGACY_NAMES if (startup_dir / name).is_file()]


def migrate_legacy_startup_entries(
    startup_dir: Path | None = None,
    backup_dir: Path | None = None,
) -> list[Path]:
    entries = legacy_startup_entries(startup_dir)
    if not entries:
        return []
    destination = backup_dir or app_data_dir() / "backups"
    destination.mkdir(parents=True, exist_ok=True)
    moved = []
    for entry in entries:
        target = destination / f"{entry.name}.before-v1.0.4"
        counter = 1
        while target.exists():
            target = destination / f"{entry.name}.before-v1.0.4.{counter}"
            counter += 1
        moved.append(Path(shutil.move(str(entry), str(target))))
    return moved


def _registry(registry: ModuleType | None) -> ModuleType:
    selected = registry or winreg
    if selected is None:
        raise OSError("Windows startup registration is unavailable on this platform.")
    return selected


def registered_startup_command(registry: ModuleType | None = None) -> str | None:
    selected = _registry(registry)
    try:
        with selected.OpenKey(selected.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = selected.QueryValueEx(key, VALUE_NAME)
            return str(value)
    except FileNotFoundError:
        return None


def set_startup_enabled(
    enabled: bool,
    executable: Path | None = None,
    registry: ModuleType | None = None,
) -> None:
    selected = _registry(registry)
    if enabled:
        command = startup_command(executable)
        if registered_startup_command(selected) == command:
            return
        with selected.CreateKeyEx(
            selected.HKEY_CURRENT_USER, RUN_KEY, 0, selected.KEY_SET_VALUE
        ) as key:
            selected.SetValueEx(key, VALUE_NAME, 0, selected.REG_SZ, command)
        return
    try:
        with selected.OpenKey(
            selected.HKEY_CURRENT_USER, RUN_KEY, 0, selected.KEY_SET_VALUE
        ) as key:
            selected.DeleteValue(key, VALUE_NAME)
    except FileNotFoundError:
        pass

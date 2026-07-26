from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon


def resource_path(name: str) -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return root / "pournotify" / "resources" / name


def application_icon() -> QIcon:
    icon = QIcon(str(resource_path("pournotify.svg")))
    if icon.isNull():
        raise RuntimeError("PourNotify application icon could not be loaded.")
    return icon

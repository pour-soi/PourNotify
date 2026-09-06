# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path


def is_external_windows_icu(binary):
    destination, source, *_ = binary
    name = Path(destination).name.casefold()
    is_icu = name == "icuuc.dll" or (name.startswith("icudt") and name.endswith(".dll"))
    source_parts = {part.casefold() for part in Path(source).parts}
    return sys.platform == "win32" and is_icu and "pyside6" not in source_parts


a = Analysis(
    ["run_pournotify.py"],
    pathex=["."],
    binaries=[],
    datas=[("pournotify/resources", "pournotify/resources")],
    hiddenimports=["PySide6.QtMultimedia"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtSql", "PySide6.QtWebEngineCore"],
    noarchive=False,
)
# Qt uses the Windows system ICU. Ignore unrelated ICU DLLs injected through build-host PATH;
# bundling those can make QtCore fail with ERROR_PROC_NOT_FOUND on otherwise supported Windows.
a.binaries = [binary for binary in a.binaries if not is_external_windows_icu(binary)]
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="PourNotify",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon="pournotify/resources/pournotify.ico",
)

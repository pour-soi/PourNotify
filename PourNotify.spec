# -*- mode: python ; coding: utf-8 -*-
a = Analysis(
    ["run_pournotify.py"],
    pathex=["."],
    binaries=[],
    datas=[],
    hiddenimports=["PySide6.QtMultimedia"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtSql", "PySide6.QtWebEngineCore"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="PourNotify",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)

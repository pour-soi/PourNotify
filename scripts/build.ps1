$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot
python -m pytest
python -m PyInstaller --clean --noconfirm PourNotify.spec

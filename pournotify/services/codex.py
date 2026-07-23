from __future__ import annotations

from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

from ..models import Category, Notification


def _project_name(workspace: Any) -> str:
    if not isinstance(workspace, str) or not workspace.strip() or "\0" in workspace:
        return "Codex"
    windows_path = PureWindowsPath(workspace)
    path = (
        windows_path
        if windows_path.drive or ("\\" in workspace and "/" not in workspace)
        else PurePosixPath(workspace)
    )
    return path.name or "Codex"


def parse_codex_event(payload: dict[str, Any]) -> Notification | None:
    if payload.get("type") != "agent-turn-complete":
        return None
    workspace = payload.get("cwd") or payload.get("workspace") or ""
    project = _project_name(workspace)
    message = str(payload.get("last-assistant-message") or "Task completed successfully.")
    return Notification(
        Category.TASK_COMPLETED, "Codex completed", message, project=project,
        deduplication_id=str(payload.get("turn-id") or ""), system_generated=True,
    )

from __future__ import annotations

from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

from ..models import Category, Notification
from .completion import CompletionDecision, classify_completion


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


def parse_codex_event(
    payload: dict[str, Any], decision: CompletionDecision | None = None
) -> Notification | None:
    if payload.get("type") != "agent-turn-complete":
        return None
    decision = decision or classify_completion(payload)
    if not decision.should_notify:
        return None
    workspace = payload.get("cwd") or payload.get("workspace") or ""
    project = _project_name(workspace)
    message = str(payload["last-assistant-message"])
    return Notification(
        Category.TASK_COMPLETED, "Codex completed", message, project=project,
        deduplication_id=str(payload.get("turn-id") or ""), system_generated=True,
    )

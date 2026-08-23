from __future__ import annotations

from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

from ..models import Category, Notification
from .completion import (
    CompletionClassification,
    CompletionDecision,
    classify_completion,
)

OWNER_ACTION_CONTENT = {
    "approval_required": (
        Category.APPROVAL_REQUIRED,
        "Codex Approval Required",
        "Codex is waiting for your approval before it can continue.",
    ),
    "required_user_input": (
        Category.INPUT_REQUIRED,
        "Codex Needs Your Input",
        "Codex is waiting for required information before it can continue.",
    ),
    "request_missing_material": (
        Category.INPUT_REQUIRED,
        "Codex Needs Your Input",
        "Codex is waiting for required material before it can continue.",
    ),
}


def _owner_action_content(reason: str) -> tuple[Category, str, str]:
    return OWNER_ACTION_CONTENT.get(
        reason,
        (
            Category.INPUT_REQUIRED,
            "Codex Needs Your Input",
            "Codex is waiting for your input or action before it can continue.",
        ),
    )


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
    if decision.classification == CompletionClassification.OWNER_ACTION_REQUIRED:
        category, title, message = _owner_action_content(decision.reason)
        return Notification(
            category,
            title,
            message,
            project=project,
            deduplication_id=str(payload.get("turn-id") or ""),
            system_generated=True,
        )
    message = str(payload["last-assistant-message"])
    return Notification(
        Category.TASK_COMPLETED, "Codex completed", message, project=project,
        deduplication_id=str(payload.get("turn-id") or ""), system_generated=True,
    )

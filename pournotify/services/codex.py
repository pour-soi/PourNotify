from __future__ import annotations

from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

from ..models import Category, Notification
from .attention import (
    AttentionDecision,
    AttentionReason,
    classify_attention,
)

ATTENTION_CONTENT = {
    AttentionReason.FINISHED: (
        Category.TASK_COMPLETED,
        "Task finished and is waiting for your next instruction.",
    ),
    AttentionReason.INPUT_REQUIRED: (
        Category.INPUT_REQUIRED,
        "Codex needs your input before it can continue.",
    ),
    AttentionReason.APPROVAL_REQUIRED: (
        Category.APPROVAL_REQUIRED,
        "Codex needs your approval before it can continue.",
    ),
}


def _project_name(workspace: Any) -> str:
    if not isinstance(workspace, str) or not workspace.strip() or "\0" in workspace:
        return "Codex"
    windows_path = PureWindowsPath(workspace)
    path = (
        windows_path
        if windows_path.drive or ("\\" in workspace and "/" not in workspace)
        else PurePosixPath(workspace)
    )
    name = " ".join(path.name.split())[:48]
    return name or "Codex"


def parse_codex_event(
    payload: dict[str, Any], decision: AttentionDecision | None = None
) -> Notification | None:
    if payload.get("type") != "agent-turn-complete":
        return None
    decision = decision or classify_attention(payload)
    if not decision.needs_attention or decision.attention_reason is None:
        return None
    workspace = payload.get("cwd") or payload.get("workspace") or ""
    project = _project_name(workspace)
    thread_id = str(payload.get("thread-id") or "")
    turn_id = str(payload.get("turn-id") or "")
    deduplication_id = f"codex:{thread_id}:{turn_id}"
    category, message = ATTENTION_CONTENT[decision.attention_reason]
    title = (
        "Codex Needs Attention"
        if project == "Codex"
        else f"Codex Needs Attention · {project}"
    )
    return Notification(
        category,
        title,
        message,
        project=project,
        deduplication_id=deduplication_id,
        system_generated=True,
    )

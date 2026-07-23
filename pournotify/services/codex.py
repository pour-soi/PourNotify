from __future__ import annotations

from pathlib import Path
from typing import Any

from ..models import Category, Notification


def parse_codex_event(payload: dict[str, Any]) -> Notification | None:
    if payload.get("type") != "agent-turn-complete":
        return None
    workspace = payload.get("cwd") or payload.get("workspace") or ""
    project = Path(workspace).name if workspace else "Codex"
    message = str(payload.get("last-assistant-message") or "Task completed successfully.")
    return Notification(
        Category.TASK_COMPLETED, "Codex completed", message, project=project,
        deduplication_id=str(payload.get("turn-id") or ""), system_generated=True,
    )

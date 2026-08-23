from __future__ import annotations

import re
from dataclasses import replace

from ..models import Category, Notification

PREVIEW_LIMIT = 250
PREVIEW_MAX_LINES = 5

SYSTEM_TITLES = {
    Category.TASK_COMPLETED: "Codex Task Completed",
    Category.TASK_FAILED: "Codex Task Failed",
    Category.APPROVAL_REQUIRED: "Codex Approval Required",
    Category.INPUT_REQUIRED: "Codex Needs Your Input",
    Category.BONUS_QUOTA: "Bonus Quota",
    Category.LOW_QUOTA: "Rate Limit Warning",
    Category.QUOTA_EXHAUSTED: "Rate Limit Warning",
    Category.PROVIDER_FAILURE: "Connection Error",
}

TITLE_ALIASES = {
    "task completed": "Codex Task Completed",
    "codex completed": "Codex Task Completed",
    "codex task complete": "Codex Task Completed",
    "task failed": "Codex Task Failed",
    "approval required": "Codex Approval Required",
    "input required": "Codex Needs Your Input",
    "bonus quota detected": "Bonus Quota",
    "low quota": "Rate Limit Warning",
    "quota exhausted": "Rate Limit Warning",
    "provider failure": "Connection Error",
    "unknown event": "Unknown Codex Event",
}

_TABLE_SEPARATOR = re.compile(
    r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$"
)
_REPEATED_CHARACTER = re.compile(r"(.)\1{19,}", re.DOTALL)


def normalize_system_title(notification: Notification) -> Notification:
    """Return canonical known-system titles without touching custom notifications."""
    if not notification.system_generated:
        return notification
    title = TITLE_ALIASES.get(notification.title.strip().casefold())
    title = title or SYSTEM_TITLES.get(notification.category)
    return replace(notification, title=title) if title else notification


def history_preview(message: str, limit: int = PREVIEW_LIMIT) -> str:
    """Create bounded, plain-text display text without changing stored content."""
    cleaned_lines: list[str] = []
    for raw_line in str(message).splitlines():
        line = raw_line.strip()
        if line.startswith("```") or _TABLE_SEPARATOR.fullmatch(line):
            continue
        if line.startswith("|") and line.endswith("|"):
            cells = [re.sub(r"\s+", " ", cell.strip()) for cell in line.strip("|").split("|")]
            line = " — ".join(cell for cell in cells if cell)
        else:
            line = re.sub(r"[ \t]+", " ", line)
        line = _REPEATED_CHARACTER.sub(lambda match: match.group(1) * 12 + "…", line)
        if line or (cleaned_lines and cleaned_lines[-1]):
            cleaned_lines.append(line)

    while cleaned_lines and not cleaned_lines[-1]:
        cleaned_lines.pop()
    compact = "\n".join(cleaned_lines[:PREVIEW_MAX_LINES])
    was_truncated = len(cleaned_lines) > PREVIEW_MAX_LINES or len(compact) > limit
    if len(compact) > limit:
        compact = compact[: limit - 1].rstrip()
    return compact + "…" if was_truncated and not compact.endswith("…") else compact


def copy_text(entry: dict[str, object]) -> str:
    return f"{entry.get('title', '')}\n\n{entry.get('message', '')}"


def entry_priority(entry: dict[str, object]) -> str:
    value = str(entry.get("priority") or "normal").lower()
    return value if value in {"low", "normal", "high", "critical"} else "normal"

from __future__ import annotations

from dataclasses import dataclass

from ..models import Category, Notification
from .codex import parse_codex_event

LONG_TEST_MESSAGE = (
    "PourNotify keeps the complete notification available while showing a concise history "
    "preview. This realistic validation paragraph includes enough detail to wrap across several "
    "lines, confirm stable card sizing, and demonstrate that users can open the details dialog "
    "to read and copy the original message without losing any content."
)

MARKDOWN_TEST_MESSAGE = (
    "| Test | Result | Evidence |\n"
    "|---|---|---|\n"
    "| Normal | Pass | Full text remains available |\n"
    "| Preview | Pass | Table separators are simplified |"
)


@dataclass(frozen=True, slots=True)
class NotificationTestCase:
    label: str
    notification: Notification
    duplicate: bool = False


def notification_test_cases() -> tuple[NotificationTestCase, ...]:
    codex = parse_codex_event({
        "type": "agent-turn-complete",
        "thread-id": "test-thread",
        "turn-id": "test-codex-complete",
        "cwd": "PourNotify",
        "input-messages": ["Inspect PourNotify and report the notification result."],
        "last-assistant-message": (
            "The requested PourNotify inspection found the expected notification result and "
            "preserved unrelated settings."
        ),
    })
    assert codex is not None
    return (
        NotificationTestCase("Codex Needs Attention: Finished", codex),
        NotificationTestCase(
            "Critical: Codex Task Failed",
            Notification(
                Category.TASK_FAILED, "Task Failed", "A critical Codex task failure was simulated.",
                system_generated=True,
            ),
        ),
        NotificationTestCase(
            "High: Bonus Quota",
            Notification(
                Category.BONUS_QUOTA, "Bonus Quota Detected",
                "A high-priority bonus quota event was simulated.", system_generated=True,
            ),
        ),
        NotificationTestCase(
            "Codex Needs Attention: Approval",
            Notification(
                Category.APPROVAL_REQUIRED,
                "Codex Needs Attention",
                "Codex needs your approval before it can continue.",
                system_generated=True,
            ),
        ),
        NotificationTestCase(
            "Long realistic notification",
            Notification(Category.TASK_COMPLETED, "Long History Preview", LONG_TEST_MESSAGE),
        ),
        NotificationTestCase(
            "Markdown table preview",
            Notification(Category.TASK_COMPLETED, "Markdown Preview Test", MARKDOWN_TEST_MESSAGE),
        ),
        NotificationTestCase(
            "Layout stress: unbroken string",
            Notification(Category.TASK_COMPLETED, "Unbroken String Layout Stress", "L" * 800),
        ),
        NotificationTestCase(
            "Duplicate merge pair",
            Notification(
                Category.TASK_COMPLETED, "Duplicate Merge Test",
                "This exact notification is sent twice and should display a duplicate count.",
            ),
            duplicate=True,
        ),
    )

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any


class Priority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class Category(StrEnum):
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    APPROVAL_REQUIRED = "approval_required"
    INPUT_REQUIRED = "input_required"
    TASK_CANCELLED = "task_cancelled"
    QUOTA_RESET = "quota_reset"
    WEEKLY_RESET = "weekly_reset"
    UNEXPECTED_QUOTA_RESET = "unexpected_quota_reset"
    BONUS_QUOTA = "bonus_quota"
    LOW_QUOTA = "low_quota"
    QUOTA_EXHAUSTED = "quota_exhausted"
    PROVIDER_FAILURE = "provider_failure"
    BARK_TEST = "bark_test"
    SYSTEM_EVENTS = "system_events"


CATEGORY_LABELS = {category: category.value.replace("_", " ").title() for category in Category}


@dataclass(slots=True)
class Notification:
    category: Category
    title: str
    message: str
    project: str = ""
    deduplication_id: str = ""
    system_generated: bool = False


@dataclass(slots=True)
class CategorySettings:
    enabled: bool = True
    bark: bool = False
    desktop: bool = True
    sound: bool = True
    history: bool = True
    sound_name: str = "Default"
    volume: int = 70
    priority: Priority = Priority.NORMAL

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> CategorySettings:
        known = {key: value[key] for key in asdict(cls()) if key in value}
        if "priority" in known:
            known["priority"] = Priority(known["priority"])
        return cls(**known)

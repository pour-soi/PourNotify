from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .models import Category, CategorySettings, Priority

CONFIG_VERSION = 1


def app_data_dir() -> Path:
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / "PourNotify"


def default_categories() -> dict[str, CategorySettings]:
    settings = {category.value: CategorySettings() for category in Category}
    for category in (Category.TASK_FAILED, Category.APPROVAL_REQUIRED,
                     Category.QUOTA_EXHAUSTED, Category.UNEXPECTED_QUOTA_RESET):
        settings[category.value].priority = Priority.CRITICAL
    settings[Category.BONUS_QUOTA.value].priority = Priority.HIGH
    settings[Category.BARK_TEST.value].history = False
    return settings


@dataclass(slots=True)
class AppConfig:
    version: int = CONFIG_VERSION
    bark_enabled: bool = False
    bark_device_key: str = ""
    bark_server_url: str = "https://api.day.app"
    bark_group: str = "PourNotify"
    bark_time_sensitive: bool = False
    quiet_hours_enabled: bool = False
    quiet_start: str = "22:00"
    quiet_end: str = "08:00"
    quiet_bark_silent: bool = True
    quiet_allow_critical: bool = True
    quiet_exceptions: list[str] = field(default_factory=lambda: [
        Category.UNEXPECTED_QUOTA_RESET.value, Category.APPROVAL_REQUIRED.value
    ])
    merge_duplicates: bool = True
    cooldown_seconds: int = 30
    max_per_minute: int = 10
    duplicate_suppression: bool = True
    history_limit: int = 500
    low_quota_threshold: int = 20
    demo_mode: bool = False
    theme: str = "system"
    start_with_windows: bool = False
    categories: dict[str, CategorySettings] = field(default_factory=default_categories)
    custom_sounds: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> AppConfig:
        defaults = cls()
        values = {key: raw[key] for key in asdict(defaults) if key in raw and key != "categories"}
        categories = default_categories()
        for name, value in raw.get("categories", {}).items():
            if name in categories and isinstance(value, dict):
                categories[name] = CategorySettings.from_dict(value)
        values["categories"] = categories
        values["version"] = CONFIG_VERSION
        return cls(**values)


class ConfigStore:
    def __init__(self, path: Path | None = None):
        self.path = path or app_data_dir() / "config.json"

    def load(self) -> AppConfig:
        if not self.path.exists():
            config = AppConfig()
            self.save(config)
            return config
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return AppConfig.from_dict(raw)
        except (OSError, ValueError, TypeError):
            return AppConfig()

    def save(self, config: AppConfig) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(config)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.path)

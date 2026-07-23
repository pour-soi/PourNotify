from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import app_data_dir
from ..models import Notification, Priority
from .content import entry_priority


class HistoryStore:
    def __init__(self, path: Path | None = None, limit: int = 500):
        self.path = path or app_data_dir() / "history.json"
        self.limit = limit

    def read(self) -> list[dict[str, Any]]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return value if isinstance(value, list) else []
        except (OSError, ValueError):
            return []

    def add(
        self,
        notification: Notification,
        status: str,
        priority: Priority,
        deduplication_id: str = "",
    ) -> None:
        entries = self.read()
        entries.append({
            "time": datetime.now().astimezone().isoformat(timespec="seconds"),
            "type": notification.category.value,
            "title": notification.title,
            "message": notification.message,
            "status": status,
            "priority": priority.value,
            "count": 1,
            "deduplication_id": deduplication_id,
        })
        self._write(entries[-self.limit :])

    def merge_last(
        self,
        notification: Notification,
        priority: Priority,
        deduplication_id: str = "",
    ) -> None:
        entries = self.read()
        for entry in reversed(entries):
            if (
                entry.get("type") == notification.category.value
                and entry.get("title") == notification.title
                and entry.get("message") == notification.message
                and (
                    not deduplication_id
                    or not entry.get("deduplication_id")
                    or entry.get("deduplication_id") == deduplication_id
                )
            ):
                entry["time"] = datetime.now().astimezone().isoformat(timespec="seconds")
                entry["count"] = int(entry.get("count", 1)) + 1
                entry["status"] = "merged_duplicate"
                entry["priority"] = priority.value
                if deduplication_id:
                    entry["deduplication_id"] = deduplication_id
                self._write(entries[-self.limit :])
                return

    def has_recent_duplicate(
        self,
        notification: Notification,
        deduplication_id: str,
        cutoff: datetime,
    ) -> bool:
        for entry in reversed(self.read()):
            timestamp = self._parse_time(entry.get("time"))
            if timestamp is None:
                continue
            comparable_cutoff = cutoff
            if timestamp.tzinfo is not None and cutoff.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=None)
            elif timestamp.tzinfo is None and cutoff.tzinfo is not None:
                comparable_cutoff = cutoff.replace(tzinfo=None)
            if timestamp <= comparable_cutoff:
                continue
            stored_id = str(entry.get("deduplication_id") or "")
            if deduplication_id:
                if stored_id == deduplication_id:
                    return True
                continue
            if (
                entry.get("type") == notification.category.value
                and entry.get("title") == notification.title
                and entry.get("message") == notification.message
            ):
                return True
        return False

    def count_delivered_since(self, cutoff: datetime) -> int:
        count = 0
        for entry in reversed(self.read()):
            timestamp = self._parse_time(entry.get("time"))
            if timestamp is None:
                continue
            comparable_cutoff = cutoff
            if timestamp.tzinfo is not None and cutoff.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=None)
            elif timestamp.tzinfo is None and cutoff.tzinfo is not None:
                comparable_cutoff = cutoff.replace(tzinfo=None)
            if timestamp <= comparable_cutoff:
                continue
            if str(entry.get("status", "")).startswith(("delivered", "partial:")):
                count += 1
        return count

    @staticmethod
    def _parse_time(value: object) -> datetime | None:
        try:
            return datetime.fromisoformat(str(value))
        except ValueError:
            return None

    def clear(self) -> None:
        self._write([])

    def export(self, destination: Path) -> None:
        entries = self.read()
        if destination.suffix.lower() == ".csv":
            with destination.open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(
                    stream,
                    fieldnames=["time", "type", "title", "message", "status", "priority", "count"],
                    extrasaction="ignore",
                )
                writer.writeheader()
                for entry in entries:
                    writer.writerow({
                        **entry,
                        "priority": entry_priority(entry),
                        "count": int(entry.get("count", 1)),
                    })
            return
        normalized = [{
            key: value
            for key, value in {
                "time": entry.get("time", ""),
                "type": entry.get("type", ""),
                "title": entry.get("title", ""),
                "message": entry.get("message", ""),
                "status": entry.get("status", ""),
                "priority": entry_priority(entry),
                "count": int(entry.get("count", 1)),
            }.items()
        } for entry in entries]
        destination.write_text(
            json.dumps(normalized, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def _write(self, entries: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.path)

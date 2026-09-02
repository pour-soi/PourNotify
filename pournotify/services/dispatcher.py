from __future__ import annotations

import hashlib
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, time, timedelta

from ..config import AppConfig
from ..models import Notification, Priority
from .content import normalize_system_title
from .delivery import BarkClient, BarkDeliveryResult, DesktopNotifier
from .history import HistoryStore
from .sounds import SoundManager


@dataclass(slots=True)
class DispatchResult:
    delivered: bool
    status: str


@dataclass(slots=True)
class DispatchTrace:
    dispatch_status: str = "not_dispatched"
    history_attempted: bool = False
    desktop_attempted: bool = False
    sound_attempted: bool = False
    bark_attempted: bool = False
    desktop_result: str = "not_attempted"
    sound_result: str = "not_attempted"
    bark_result: str = "not_attempted"
    history_result: str = "not_attempted"
    http_status: int | None = None
    bark_response: str = ""
    exception: str = ""
    completion_classification: str = ""
    completion_reason: str = ""
    attention_state: str = ""
    attention_reason: str = ""
    classification_reason: str = ""
    classifier_version: str = ""
    observer_version: str = ""
    codex_thread_source: str = ""
    detected_lifecycle: str = ""
    detection_reason: str = ""
    dedupe_result: str = ""
    observation_only: bool = False

    def add_exception(self, channel: str, error: Exception) -> None:
        detail = f"{channel}: {type(error).__name__}: {error}"
        self.exception = f"{self.exception}; {detail}" if self.exception else detail


class NotificationDispatcher:
    def __init__(self, config: AppConfig, history: HistoryStore, desktop: DesktopNotifier,
                 sounds: SoundManager, bark: BarkClient | None = None,
                 clock: Callable[[], datetime] | None = None):
        self.config = config
        self.history = history
        self.desktop = desktop
        self.sounds = sounds
        self.bark = bark or BarkClient()
        self.clock = clock or datetime.now
        self._recent: dict[str, datetime] = {}
        self._minute: deque[datetime] = deque()
        self._duplicate_counts: defaultdict[str, int] = defaultdict(int)

    def dispatch(
        self, notification: Notification, trace: DispatchTrace | None = None
    ) -> DispatchResult:
        trace = trace or DispatchTrace()
        notification = normalize_system_title(notification)
        settings = self.config.categories[notification.category.value]
        if not settings.enabled:
            return DispatchResult(False, "disabled")
        now = self.clock()
        key = notification.deduplication_id or hashlib.sha256(
            f"{notification.category.value}\0{notification.title}\0{notification.message}".encode()
        ).hexdigest()
        cutoff = now - timedelta(seconds=max(0, self.config.cooldown_seconds))
        persisted_duplicate = self.history.has_recent_duplicate(notification, key, cutoff)
        oldest = datetime.min.replace(tzinfo=now.tzinfo)
        if (
            self._recent.get(key, oldest) > cutoff or persisted_duplicate
        ) and self.config.merge_duplicates:
            self._duplicate_counts[key] += 1
            if settings.history:
                trace.history_attempted = True
                try:
                    self.history.merge_last(notification, settings.priority, key)
                    trace.history_result = "merged_duplicate"
                except Exception as error:
                    trace.history_result = "error"
                    trace.add_exception("history", error)
                    raise
            return DispatchResult(False, "merged_duplicate")
        if self.config.duplicate_suppression and (
            self._recent.get(key, oldest) > cutoff or persisted_duplicate
        ):
            self._duplicate_counts[key] += 1
            return DispatchResult(False, "duplicate_suppressed")
        minute_ago = now - timedelta(minutes=1)
        while self._minute and self._minute[0] <= minute_ago:
            self._minute.popleft()
        persisted_per_minute = self.history.count_delivered_since(minute_ago)
        if max(len(self._minute), persisted_per_minute) >= max(1, self.config.max_per_minute):
            return DispatchResult(False, "rate_limited")
        self._recent[key] = now
        self._minute.append(now)
        quiet = self._is_quiet(now.time())
        bypass = (
            settings.priority == Priority.CRITICAL and self.config.quiet_allow_critical
        ) or notification.category.value in self.config.quiet_exceptions
        failures: list[str] = []
        delivery_notification = replace(
            notification,
            message=(
                notification.message[:497] + "..."
                if len(notification.message) > 500
                else notification.message
            ),
        )
        if settings.desktop:
            trace.desktop_attempted = True
            try:
                self.desktop.send(delivery_notification, settings.priority)
                trace.desktop_result = "attempted_no_exception"
            except Exception as error:  # noqa: BLE001 - isolate desktop adapter failures
                failures.append("desktop")
                trace.desktop_result = "error"
                trace.add_exception("desktop", error)
        if settings.sound and (not quiet or bypass):
            trace.sound_attempted = True
            self.sounds.play(settings.sound_name, settings.volume, self.config.custom_sounds)
            trace.sound_result = "attempted_no_exception"
        if settings.bark and self.config.bark_enabled and self.config.bark_device_key:
            trace.bark_attempted = True
            try:
                bark_result = self.bark.send(
                    self.config.bark_server_url, self.config.bark_device_key, delivery_notification,
                    group=self.config.bark_group, sound=settings.sound_name,
                    time_sensitive=self.config.bark_time_sensitive,
                    silent=quiet and self.config.quiet_bark_silent and not bypass,
                )
                trace.bark_result = "success"
                if isinstance(bark_result, BarkDeliveryResult):
                    trace.http_status = bark_result.http_status
                    trace.bark_response = bark_result.response
            except Exception as error:  # noqa: BLE001 - isolate Bark adapter failures
                failures.append("bark")
                trace.bark_result = "error"
                trace.http_status = getattr(error, "http_status", None)
                trace.bark_response = str(getattr(error, "response", ""))
                trace.add_exception("bark", error)
        status = "attempted_with_errors:" + ",".join(failures) if failures else "attempted"
        if settings.history:
            trace.history_attempted = True
            try:
                self.history.add(notification, status, settings.priority, key)
                trace.history_result = "success"
            except Exception as error:
                trace.history_result = "error"
                trace.add_exception("history", error)
                raise
        return DispatchResult(not failures, status)

    def _is_quiet(self, current: time) -> bool:
        if not self.config.quiet_hours_enabled:
            return False
        start = time.fromisoformat(self.config.quiet_start)
        end = time.fromisoformat(self.config.quiet_end)
        if start == end:
            return True
        return start <= current < end if start < end else current >= start or current < end

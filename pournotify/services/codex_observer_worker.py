from __future__ import annotations

import os
import queue
import threading
import time
from pathlib import Path
from typing import Any

from .codex_observer import CodexRolloutObserver, ObserverMetrics

DEFAULT_POLL_INTERVAL_SECONDS = 5.0
SCHEMA_DIAGNOSTIC_INTERVAL_SECONDS = 5 * 60
MAX_PENDING_EVENTS = 100


def codex_sessions_root() -> Path:
    configured = os.environ.get("CODEX_HOME", "")
    if configured.strip() and "\0" not in configured:
        return Path(configured).expanduser() / "sessions"
    return Path.home() / ".codex" / "sessions"


class CodexObserverWorker:
    """Runs rollout I/O away from the UI/IPC thread and queues safe results."""

    def __init__(
        self,
        sessions_root: Path,
        *,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    ) -> None:
        self._poll_interval_seconds = max(0.1, poll_interval_seconds)
        self._candidate_queue: queue.Queue[tuple[int, dict[str, Any]]] = queue.Queue(
            maxsize=MAX_PENDING_EVENTS
        )
        self._diagnostic_queue: queue.Queue[tuple[str, str]] = queue.Queue(
            maxsize=MAX_PENDING_EVENTS
        )
        self._state_lock = threading.Lock()
        self._requested_enabled = False
        self._epoch = 0
        self._applied_epoch = 0
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._observer = CodexRolloutObserver(sessions_root, self._queue_candidate)

    @property
    def enabled(self) -> bool:
        with self._state_lock:
            return self._requested_enabled

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run,
            name="PourNotify-CodexObserver",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._wake_event.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1)

    def set_enabled(self, enabled: bool) -> None:
        with self._state_lock:
            if enabled == self._requested_enabled:
                return
            self._requested_enabled = enabled
            self._epoch += 1
        self._wake_event.set()

    def drain_candidates(self) -> list[dict[str, Any]]:
        with self._state_lock:
            enabled = self._requested_enabled
            epoch = self._epoch
        candidates: list[dict[str, Any]] = []
        while True:
            try:
                candidate_epoch, payload = self._candidate_queue.get_nowait()
            except queue.Empty:
                break
            if enabled and candidate_epoch == epoch:
                candidates.append(payload)
        return candidates

    def drain_diagnostics(self) -> list[tuple[str, str]]:
        diagnostics: list[tuple[str, str]] = []
        while True:
            try:
                diagnostics.append(self._diagnostic_queue.get_nowait())
            except queue.Empty:
                return diagnostics

    def metrics_snapshot(self) -> ObserverMetrics:
        return self._observer.metrics_snapshot()

    def _queue_candidate(self, payload: dict[str, Any]) -> None:
        try:
            self._candidate_queue.put_nowait((self._applied_epoch, payload))
        except queue.Full:
            self._queue_diagnostic(
                "observer_queue_full",
                "local_rollout_observer_queue_full",
            )

    def _queue_diagnostic(self, status: str, reason: str) -> None:
        try:
            self._diagnostic_queue.put_nowait((status, reason))
        except queue.Full:
            pass

    def _requested_state(self) -> tuple[bool, int]:
        with self._state_lock:
            return self._requested_enabled, self._epoch

    def _run(self) -> None:
        applied_enabled = False
        failure_active = False
        last_schema_diagnostic_at = float("-inf")
        next_poll_at = time.monotonic()
        while not self._stop_event.is_set():
            requested_enabled, requested_epoch = self._requested_state()
            if requested_epoch != self._applied_epoch:
                try:
                    self._observer.set_enabled(requested_enabled)
                except Exception:  # noqa: BLE001 - preserve normal notify on observer failure
                    self._queue_diagnostic(
                        "observer_error",
                        "local_rollout_observer_error",
                    )
                    requested_enabled = False
                self._applied_epoch = requested_epoch
                applied_enabled = requested_enabled
                failure_active = False
                next_poll_at = time.monotonic()

            now = time.monotonic()
            if applied_enabled and now >= next_poll_at:
                before = self._observer.metrics_snapshot()
                try:
                    self._observer.poll_once()
                except Exception:  # noqa: BLE001 - preserve normal notify on observer failure
                    self._queue_diagnostic(
                        "observer_error",
                        "local_rollout_observer_error",
                    )
                    failure_active = True
                else:
                    after = self._observer.metrics_snapshot()
                    if (
                        after.schema_rejections > before.schema_rejections
                        and now - last_schema_diagnostic_at
                        >= SCHEMA_DIAGNOSTIC_INTERVAL_SECONDS
                    ):
                        self._queue_diagnostic(
                            "observer_schema_mismatch",
                            "local_rollout_schema_mismatch",
                        )
                        last_schema_diagnostic_at = now
                    failed = (
                        after.source_errors > before.source_errors
                        or after.read_errors > before.read_errors
                    )
                    if failed and not failure_active:
                        self._queue_diagnostic(
                            "observer_source_unavailable",
                            "local_rollout_source_unavailable",
                        )
                    failure_active = failed
                next_poll_at = time.monotonic() + self._poll_interval_seconds

            timeout = (
                max(0.05, next_poll_at - time.monotonic())
                if applied_enabled
                else None
            )
            self._wake_event.wait(timeout)
            self._wake_event.clear()

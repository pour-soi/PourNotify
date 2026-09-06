from __future__ import annotations

import threading

from pournotify.services import codex_observer_worker
from pournotify.services.codex_observer import ObserverMetrics
from pournotify.services.codex_observer_worker import (
    CodexObserverWorker,
    codex_sessions_root,
)


class FakeObserver:
    enabled_thread = 0
    enabled_event = threading.Event()
    source_accesses = 0

    def __init__(self, sessions_root, emit):
        self.emit = emit

    def set_enabled(self, enabled):
        self.__class__.enabled_thread = threading.get_ident()
        self.__class__.source_accesses += 1
        self.__class__.enabled_event.set()

    def poll_once(self):
        self.__class__.source_accesses += 1

    @staticmethod
    def metrics_snapshot():
        return ObserverMetrics()


class SchemaRejectingObserver:
    polled = threading.Event()

    def __init__(self, sessions_root, emit):
        self.metrics = ObserverMetrics()

    def set_enabled(self, enabled):
        pass

    def poll_once(self):
        self.metrics.schema_rejections += 1
        self.__class__.polled.set()

    def metrics_snapshot(self):
        return ObserverMetrics(schema_rejections=self.metrics.schema_rejections)


def test_worker_does_no_source_io_while_disabled_and_enables_off_caller_thread(
    tmp_path, monkeypatch
):
    FakeObserver.enabled_event.clear()
    FakeObserver.source_accesses = 0
    monkeypatch.setattr(codex_observer_worker, "CodexRolloutObserver", FakeObserver)
    caller_thread = threading.get_ident()
    worker = CodexObserverWorker(tmp_path, poll_interval_seconds=60)
    worker.start()

    assert FakeObserver.source_accesses == 0
    worker.set_enabled(True)
    assert FakeObserver.enabled_event.wait(2)

    worker.stop()
    assert FakeObserver.enabled_thread != caller_thread
    assert FakeObserver.source_accesses >= 1


def test_worker_reports_schema_mismatch_without_exposing_content(tmp_path, monkeypatch):
    SchemaRejectingObserver.polled.clear()
    monkeypatch.setattr(
        codex_observer_worker,
        "CodexRolloutObserver",
        SchemaRejectingObserver,
    )
    worker = CodexObserverWorker(tmp_path, poll_interval_seconds=60)
    worker.start()
    worker.set_enabled(True)

    assert SchemaRejectingObserver.polled.wait(2)
    diagnostics = worker.drain_diagnostics()
    worker.stop()

    assert diagnostics == [
        ("observer_schema_mismatch", "local_rollout_schema_mismatch")
    ]


def test_codex_sessions_root_honors_configured_codex_home(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    assert codex_sessions_root() == tmp_path / "sessions"


def test_codex_sessions_root_uses_default_when_codex_home_is_unset(monkeypatch):
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.setattr(
        codex_observer_worker.Path,
        "home",
        lambda: codex_observer_worker.Path("X:/home"),
    )

    assert codex_sessions_root() == codex_observer_worker.Path("X:/home/.codex/sessions")


def test_candidate_queue_is_bounded_and_overflow_diagnostic_is_content_free(tmp_path):
    worker = CodexObserverWorker(tmp_path)
    worker._applied_epoch = 1
    worker._requested_enabled = True
    worker._epoch = 1

    for index in range(codex_observer_worker.MAX_PENDING_EVENTS + 1):
        worker._queue_candidate({"private": f"raw-{index}"})

    candidates = worker.drain_candidates()
    diagnostics = worker.drain_diagnostics()

    assert len(candidates) == codex_observer_worker.MAX_PENDING_EVENTS
    assert diagnostics == [
        ("observer_queue_full", "local_rollout_observer_queue_full")
    ]
    assert "raw-" not in repr(diagnostics)

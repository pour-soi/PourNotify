from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import deque
from collections.abc import Callable
from logging.handlers import RotatingFileHandler
from time import monotonic, perf_counter
from typing import Any

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from .config import ConfigStore, app_data_dir
from .resources import application_icon
from .services.attention import AttentionDecision, AttentionState, classify_attention
from .services.codex import parse_codex_event
from .services.codex_observer import (
    OBSERVER_VERSION,
    USER_THREAD_SOURCES,
    resolve_codex_thread_source,
)
from .services.codex_observer_worker import CodexObserverWorker, codex_sessions_root
from .services.diagnostics import NotificationDiagnostics
from .services.dispatcher import DispatchTrace
from .services.ipc import (
    NotificationIpcServer,
    send_control_to_running_instance,
    send_observation_to_running_instance,
    send_to_running_instance,
)
from .services.lifecycle_ledger import CodexLifecycleLedger, LifecycleLedgerError
from .services.startup import set_startup_enabled, startup_supported
from .ui.main_window import MainWindow

LOGGER = logging.getLogger(__name__)


def configure_logging() -> None:
    folder = app_data_dir() / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(folder / "pournotify.log", maxBytes=1_000_000, backupCount=3)
    logging.basicConfig(level=logging.INFO, handlers=[handler], format="%(asctime)s %(levelname)s %(message)s")


def record_observer_diagnostic(
    diagnostics: NotificationDiagnostics,
    status: str,
    reason: str,
) -> None:
    trace = DispatchTrace(
        dispatch_status=status,
        observer_version=OBSERVER_VERSION,
        attention_state="ambiguous",
        classification_reason=reason,
        completion_classification="ambiguous",
        completion_reason=reason,
        detected_lifecycle="suppressed",
        detection_reason=reason,
        dedupe_result="not_applicable",
    )
    diagnostics.record(
        {"type": "codex-local-observer", "event_type": status},
        "codex_local_fallback",
        trace,
        perf_counter(),
        arguments=list(sys.argv),
    )


def dispatch_codex_payload(
    window: MainWindow,
    payload: str,
    diagnostics: NotificationDiagnostics | None = None,
    notify_source: str = "command_line",
    observation_only: bool = False,
    lifecycle_ledger: CodexLifecycleLedger | None = None,
    observer_version: str = "",
    retry_unattempted: Callable[[], None] | None = None,
    thread_source_resolver: Callable[[str], str] | None = None,
) -> bool:
    started = perf_counter()
    trace = DispatchTrace()
    received_payload: Any = payload
    exception = ""
    try:
        received_payload = json.loads(payload)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        exception = f"{type(error).__name__}: {error}"
        trace.dispatch_status = "malformed_payload"
        LOGGER.warning("Ignored malformed Codex notification payload")
        result = False
    else:
        try:
            if not isinstance(received_payload, dict):
                trace.dispatch_status = "malformed_payload"
                notification = None
            elif received_payload.get("type") == "agent-turn-complete":
                resolved_source = ""
                if (
                    thread_source_resolver is not None
                    and notify_source != "codex_local_fallback"
                ):
                    thread_id = received_payload.get("thread-id")
                    if isinstance(thread_id, str):
                        try:
                            resolved_source = thread_source_resolver(thread_id)
                        except Exception:  # noqa: BLE001 - fail closed on local state drift
                            resolved_source = ""
                    trace.codex_thread_source = resolved_source
                if thread_source_resolver is not None and not resolved_source and (
                    notify_source != "codex_local_fallback"
                ):
                    decision = AttentionDecision(
                        AttentionState.AMBIGUOUS,
                        "unverified_thread_source",
                    )
                elif resolved_source and resolved_source not in USER_THREAD_SOURCES:
                    decision = AttentionDecision(
                        AttentionState.SUPPRESSED_INTERNAL,
                        (
                            "subagent_thread"
                            if resolved_source == "subagent"
                            else "non_user_thread_source"
                        ),
                    )
                else:
                    decision = classify_attention(
                        received_payload,
                        local_terminal_evidence=(
                            (
                                notify_source == "codex_local_fallback"
                                and observer_version == OBSERVER_VERSION
                            )
                            or resolved_source in USER_THREAD_SOURCES
                        ),
                    )
                if (
                    notify_source == "codex_local_fallback"
                    and observer_version == OBSERVER_VERSION
                ):
                    trace.codex_thread_source = "observer_verified_user"
                trace.attention_state = decision.state.value
                trace.attention_reason = (
                    decision.attention_reason.value if decision.attention_reason else ""
                )
                trace.classification_reason = decision.classification_reason
                trace.completion_classification = decision.state.value
                trace.completion_reason = decision.classification_reason
                trace.classifier_version = decision.classifier_version
                trace.detected_lifecycle = decision.state.value
                trace.detection_reason = decision.classification_reason
                trace.observer_version = observer_version
                notification = parse_codex_event(received_payload, decision)
            else:
                notification = None
        except Exception as error:
            exception = f"{type(error).__name__}: {error}"
            trace.dispatch_status = "parse_error"
            raise
        if not isinstance(received_payload, dict):
            result = False
        elif received_payload.get("type") != "agent-turn-complete":
            trace.dispatch_status = "unsupported_event"
            LOGGER.info("Ignored unsupported Codex notification type")
            result = False
        elif observation_only:
            trace.observation_only = True
            trace.dispatch_status = "observation_only"
            trace.dedupe_result = "not_claimed"
            result = False
        elif notification is None:
            trace.dispatch_status = "attention_suppressed"
            LOGGER.info("Suppressed Codex turn that does not need attention")
            result = False
        else:
            claim_created = False
            thread_id = received_payload.get("thread-id")
            turn_id = received_payload.get("turn-id")
            if not all(isinstance(value, str) and value.strip() for value in (thread_id, turn_id)):
                trace.dispatch_status = "malformed_lifecycle_identity"
                trace.dedupe_result = "invalid_identity"
                LOGGER.warning("Ignored Codex lifecycle event without stable identity")
                result = False
                return result
            if lifecycle_ledger is not None:
                try:
                    claim = lifecycle_ledger.claim(thread_id, turn_id, notify_source)
                except (LifecycleLedgerError, ValueError) as error:
                    trace.dedupe_result = "ledger_unavailable"
                    if notify_source == "codex_local_fallback":
                        trace.dispatch_status = "fallback_ledger_unavailable"
                        exception = f"{type(error).__name__}: {error}"
                        LOGGER.warning("Suppressed fallback event because deduplication is unavailable")
                        result = False
                        return result
                    LOGGER.warning("Lifecycle ledger unavailable; preserving normal notify path")
                else:
                    if not claim.claimed:
                        trace.dedupe_result = "already_claimed"
                        trace.dispatch_status = "lifecycle_duplicate"
                        result = False
                        return result
                    trace.dedupe_result = "claimed"
                    claim_created = True
            try:
                dispatch_result = window.dispatcher.dispatch(notification, trace=trace)
                trace.dispatch_status = dispatch_result.status
                if dispatch_result.status == "rate_limited" and claim_created:
                    try:
                        released = lifecycle_ledger.release(thread_id, turn_id, notify_source)
                    except LifecycleLedgerError as error:
                        released = False
                        trace.add_exception("lifecycle_ledger", error)
                    trace.dedupe_result = "released_for_retry" if released else "release_failed"
                    if released and retry_unattempted is not None:
                        retry_unattempted()
                    result = False
                else:
                    result = True
            except Exception as error:
                exception = f"{type(error).__name__}: {error}"
                raise
    finally:
        if diagnostics is not None:
            diagnostics.record(
                received_payload,
                notify_source,
                trace,
                started,
                exception=exception,
                arguments=list(sys.argv),
            )
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--notify", help="Codex notify JSON payload")
    mode.add_argument(
        "--observe-notify",
        help="Classify a Codex notify JSON payload without delivering or writing History",
    )
    mode.add_argument(
        "--background",
        action="store_true",
        help="Start resident notification services without opening the main window",
    )
    return parser


def launch_action(args: argparse.Namespace) -> str:
    if args.notify:
        return "exit" if send_to_running_instance(args.notify) else "notify"
    if getattr(args, "observe_notify", None):
        return (
            "exit"
            if send_observation_to_running_instance(args.observe_notify)
            else "observe_notify"
        )
    command = "ping" if args.background else "show"
    if send_control_to_running_instance(command):
        return "exit"
    return "background" if args.background else "show"


def should_create_codex_observer(action: str, platform: str | None = None) -> bool:
    return action in {"background", "show"} and (platform or sys.platform) == "win32"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging()
    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(application_icon())
    action = launch_action(args)
    if action == "exit":
        return 0
    store = ConfigStore()
    diagnostics = NotificationDiagnostics()
    config = store.load()
    lifecycle_ledger = CodexLifecycleLedger()
    sessions_root = codex_sessions_root()
    thread_source_resolver = lambda thread_id: resolve_codex_thread_source(
        sessions_root, thread_id
    )
    if (
        not args.notify
        and not args.observe_notify
        and config.start_with_windows
        and startup_supported()
    ):
        try:
            set_startup_enabled(True)
        except OSError as error:
            LOGGER.warning("Unable to refresh Windows startup registration: %s", error)
    window = MainWindow(config, store)

    NotificationIpcServer(
        lambda payload: dispatch_codex_payload(
            window,
            payload,
            diagnostics,
            notify_source="ipc",
            lifecycle_ledger=lifecycle_ledger,
            thread_source_resolver=thread_source_resolver,
        ),
        control_handler=lambda command: window.show_and_activate()
        if command == "show"
        else None,
        observation_handler=lambda payload: dispatch_codex_payload(
            window,
            payload,
            diagnostics,
            notify_source="observation_ipc",
            observation_only=True,
            lifecycle_ledger=lifecycle_ledger,
            thread_source_resolver=thread_source_resolver,
        ),
        parent=window,
    )
    observer_worker = None
    observer_timer = None
    if should_create_codex_observer(action):
        observer_worker = CodexObserverWorker(sessions_root)
        observer_started = False
        observer_timer = QTimer(window)
        observer_timer.setInterval(250)
        fallback_retries: deque[tuple[float, int, dict[str, Any]]] = deque()

        def schedule_fallback_retry(payload: dict[str, Any], attempt: int) -> None:
            if attempt <= 4 and len(fallback_retries) < 100:
                fallback_retries.append((monotonic() + 20, attempt, payload))

        def deliver_fallback(payload: dict[str, Any], attempt: int = 0) -> None:
            dispatch_codex_payload(
                window,
                json.dumps(payload, ensure_ascii=False),
                diagnostics,
                notify_source="codex_local_fallback",
                lifecycle_ledger=lifecycle_ledger,
                observer_version=OBSERVER_VERSION,
                retry_unattempted=lambda: schedule_fallback_retry(payload, attempt + 1),
            )

        def poll_observer() -> None:
            for status, reason in observer_worker.drain_diagnostics():
                record_observer_diagnostic(
                    diagnostics,
                    status,
                    reason,
                )
            for payload in observer_worker.drain_candidates():
                deliver_fallback(payload)
            now = monotonic()
            for _ in range(len(fallback_retries)):
                due_at, attempt, payload = fallback_retries.popleft()
                if due_at <= now:
                    deliver_fallback(payload, attempt)
                else:
                    fallback_retries.append((due_at, attempt, payload))

        observer_timer.timeout.connect(poll_observer)

        def set_fallback_enabled(enabled: bool) -> None:
            nonlocal observer_started
            if not enabled:
                fallback_retries.clear()
                observer_worker.set_enabled(False)
                observer_timer.stop()
                return
            if not observer_started:
                observer_worker.start()
                observer_started = True
            observer_worker.set_enabled(enabled)
            observer_timer.start()

        window.settings_page.fallback_changed = set_fallback_enabled
        set_fallback_enabled(config.codex_local_fallback_enabled)
        app.aboutToQuit.connect(observer_worker.stop)
    if action in {"notify", "observe_notify"}:
        notification_payload = args.notify or args.observe_notify
        dispatch_codex_payload(
            window,
            notification_payload,
            diagnostics,
            notify_source=(
                "command_line" if action == "notify" else "observation_command_line"
            ),
            observation_only=action == "observe_notify",
            lifecycle_ledger=lifecycle_ledger,
            thread_source_resolver=thread_source_resolver,
        )
        QTimer.singleShot(2000, app.quit)
    elif action == "show":
        window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

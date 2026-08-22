from __future__ import annotations

import argparse
import json
import logging
import sys
from logging.handlers import RotatingFileHandler
from time import perf_counter
from typing import Any

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from .config import ConfigStore, app_data_dir
from .resources import application_icon
from .services.codex import parse_codex_event
from .services.completion import classify_completion
from .services.diagnostics import NotificationDiagnostics
from .services.dispatcher import DispatchTrace
from .services.ipc import (
    NotificationIpcServer,
    send_control_to_running_instance,
    send_observation_to_running_instance,
    send_to_running_instance,
)
from .services.startup import set_startup_enabled, startup_supported
from .ui.main_window import MainWindow

LOGGER = logging.getLogger(__name__)


def configure_logging() -> None:
    folder = app_data_dir() / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(folder / "pournotify.log", maxBytes=1_000_000, backupCount=3)
    logging.basicConfig(level=logging.INFO, handlers=[handler], format="%(asctime)s %(levelname)s %(message)s")


def dispatch_codex_payload(
    window: MainWindow,
    payload: str,
    diagnostics: NotificationDiagnostics | None = None,
    notify_source: str = "command_line",
    observation_only: bool = False,
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
                decision = classify_completion(received_payload)
                trace.completion_classification = decision.classification.value
                trace.completion_reason = decision.reason
                trace.classifier_version = decision.classifier_version
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
            result = False
        elif notification is None:
            trace.dispatch_status = "completion_suppressed"
            LOGGER.info("Suppressed non-final Codex turn")
            result = False
        else:
            try:
                dispatch_result = window.dispatcher.dispatch(notification, trace=trace)
                trace.dispatch_status = dispatch_result.status
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


def matches_observation_thread(payload: str, observed_thread_id: str | None) -> bool:
    if not observed_thread_id:
        return False
    try:
        received_payload = json.loads(payload)
    except (TypeError, ValueError, json.JSONDecodeError):
        return False
    return (
        isinstance(received_payload, dict)
        and received_payload.get("thread-id") == observed_thread_id
    )


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
    parser.add_argument(
        "--observe-thread-id",
        help="Route one exact thread through diagnostics-only observation while resident",
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

    def handle_ipc_payload(payload: str) -> bool:
        observation_only = matches_observation_thread(payload, args.observe_thread_id)
        return dispatch_codex_payload(
            window,
            payload,
            diagnostics,
            notify_source="observation_thread_ipc" if observation_only else "ipc",
            observation_only=observation_only,
        )

    NotificationIpcServer(
        handle_ipc_payload,
        control_handler=lambda command: window.show_and_activate()
        if command == "show"
        else None,
        observation_handler=lambda payload: dispatch_codex_payload(
            window,
            payload,
            diagnostics,
            notify_source="observation_ipc",
            observation_only=True,
        ),
        parent=window,
    )
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
        )
        QTimer.singleShot(2000, app.quit)
    elif action == "show":
        window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

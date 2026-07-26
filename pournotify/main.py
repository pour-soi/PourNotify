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
from .services.codex import parse_codex_event
from .services.diagnostics import NotificationDiagnostics
from .services.dispatcher import DispatchTrace
from .services.ipc import NotificationIpcServer, send_to_running_instance
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
            notification = parse_codex_event(received_payload)
        except Exception as error:
            exception = f"{type(error).__name__}: {error}"
            trace.dispatch_status = "parse_error"
            raise
        if notification is None:
            trace.dispatch_status = "unsupported_event"
            LOGGER.info("Ignored unsupported Codex notification type")
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--notify", help="Codex notify JSON payload")
    args = parser.parse_args()
    configure_logging()
    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    if args.notify and send_to_running_instance(args.notify):
        return 0
    store = ConfigStore()
    diagnostics = NotificationDiagnostics()
    window = MainWindow(store.load(), store)
    NotificationIpcServer(
        lambda payload: dispatch_codex_payload(
            window, payload, diagnostics, notify_source="ipc"
        ),
        window,
    )
    if args.notify:
        dispatch_codex_payload(
            window, args.notify, diagnostics, notify_source="command_line"
        )
        QTimer.singleShot(2000, app.quit)
    else:
        window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

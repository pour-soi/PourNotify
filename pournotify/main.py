from __future__ import annotations

import argparse
import json
import logging
import sys
from logging.handlers import RotatingFileHandler

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from .config import ConfigStore, app_data_dir
from .services.codex import parse_codex_event
from .services.ipc import NotificationIpcServer, send_to_running_instance
from .ui.main_window import MainWindow


def configure_logging() -> None:
    folder = app_data_dir() / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(folder / "pournotify.log", maxBytes=1_000_000, backupCount=3)
    logging.basicConfig(level=logging.INFO, handlers=[handler], format="%(asctime)s %(levelname)s %(message)s")


def dispatch_codex_payload(window: MainWindow, payload: str) -> bool:
    try:
        notification = parse_codex_event(json.loads(payload))
    except (TypeError, ValueError, json.JSONDecodeError):
        logging.warning("Ignored malformed Codex notification payload")
        return False
    if notification is None:
        logging.info("Ignored unsupported Codex notification type")
        return False
    window.dispatcher.dispatch(notification)
    return True


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
    window = MainWindow(store.load(), store)
    NotificationIpcServer(
        lambda payload: dispatch_codex_payload(window, payload), window
    )
    if args.notify:
        dispatch_codex_payload(window, args.notify)
        QTimer.singleShot(2000, app.quit)
    else:
        window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

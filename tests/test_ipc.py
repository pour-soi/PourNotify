import subprocess
import sys

from PySide6.QtNetwork import QLocalServer
from PySide6.QtWidgets import QApplication

from pournotify.main import dispatch_codex_payload
from pournotify.services.ipc import (
    SERVER_NAME, NotificationIpcServer,
)


def app():
    return QApplication.instance() or QApplication([])


def test_local_ipc_forwards_payload_to_running_instance():
    qt_app = app()
    received = []
    test_server_name = SERVER_NAME + "-pytest"
    server = NotificationIpcServer(received.append, server_name=test_server_name)
    client = subprocess.Popen(
        [
            sys.executable,
            "-c",
                "from pournotify.services.ipc import send_to_running_instance;"
                "import sys;"
                "raise SystemExit(0 if send_to_running_instance("
                "'{\"type\":\"agent-turn-complete\"}',server_name=sys.argv[1]) else 1)",
                test_server_name,
            ],
    )
    while client.poll() is None:
        qt_app.processEvents()
    for _ in range(5):
        qt_app.processEvents()
    assert client.returncode == 0
    assert received == ['{"type":"agent-turn-complete"}']
    server.server.close()
    QLocalServer.removeServer(test_server_name)


class DispatcherRecorder:
    def __init__(self):
        self.items = []

    def dispatch(self, notification):
        self.items.append(notification)


class WindowRecorder:
    def __init__(self):
        self.dispatcher = DispatcherRecorder()


def test_malformed_and_unknown_payloads_fail_safely():
    window = WindowRecorder()
    assert dispatch_codex_payload(window, "{not-json") is False
    assert dispatch_codex_payload(window, '{"type":"future-event"}') is False
    assert window.dispatcher.items == []

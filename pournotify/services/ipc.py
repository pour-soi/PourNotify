from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject
from PySide6.QtNetwork import QLocalServer, QLocalSocket

SERVER_NAME = "PourNotify-v1-notifications"
CONTROL_PREFIX = "pournotify-control:"
OBSERVATION_PREFIX = "pournotify-observation:"


def send_to_running_instance(
    payload: str,
    timeout_ms: int = 750,
    server_name: str = SERVER_NAME,
) -> bool:
    return _send_to_running_instance(payload, timeout_ms, server_name)


def send_control_to_running_instance(
    command: str,
    timeout_ms: int = 750,
    server_name: str = SERVER_NAME,
) -> bool:
    if command not in {"ping", "show"}:
        raise ValueError(f"Unsupported PourNotify control command: {command}")
    return _send_to_running_instance(CONTROL_PREFIX + command, timeout_ms, server_name)


def send_observation_to_running_instance(
    payload: str,
    timeout_ms: int = 750,
    server_name: str = SERVER_NAME,
) -> bool:
    return _send_to_running_instance(OBSERVATION_PREFIX + payload, timeout_ms, server_name)


def _send_to_running_instance(payload: str, timeout_ms: int, server_name: str) -> bool:
    socket = QLocalSocket()
    socket.connectToServer(server_name)
    if not socket.waitForConnected(timeout_ms):
        return False
    written = socket.write(payload.encode("utf-8") + b"\n")
    socket.flush()
    sent = written >= 0 and (
        socket.bytesToWrite() == 0 or socket.waitForBytesWritten(timeout_ms)
    )
    socket.disconnectFromServer()
    return sent


class NotificationIpcServer(QObject):
    def __init__(
        self,
        handler: Callable[[str], None],
        control_handler: Callable[[str], None] | None = None,
        observation_handler: Callable[[str], None] | None = None,
        parent: QObject | None = None,
        server_name: str = SERVER_NAME,
    ):
        super().__init__(parent)
        self.handler = handler
        self.control_handler = control_handler
        self.observation_handler = observation_handler
        self.server_name = server_name
        self.server = QLocalServer(self)
        self.connections: set[QLocalSocket] = set()
        QLocalServer.removeServer(server_name)
        if not self.server.listen(server_name):
            raise RuntimeError("Unable to start the local PourNotify notification server.")
        self.server.newConnection.connect(self._accept_connections)

    def _accept_connections(self) -> None:
        while self.server.hasPendingConnections():
            connection = self.server.nextPendingConnection()
            if connection is None:
                continue
            self.connections.add(connection)
            connection.readyRead.connect(lambda item=connection: self._read(item))
            connection.disconnected.connect(lambda item=connection: self._discard(item))

    def _read(self, connection: QLocalSocket) -> None:
        while connection.canReadLine():
            payload = bytes(connection.readLine()).rstrip(b"\r\n").decode(
                "utf-8", errors="replace"
            )
            if payload:
                if payload.startswith(CONTROL_PREFIX) and self.control_handler is not None:
                    self.control_handler(payload.removeprefix(CONTROL_PREFIX))
                elif payload.startswith(OBSERVATION_PREFIX):
                    if self.observation_handler is not None:
                        self.observation_handler(payload.removeprefix(OBSERVATION_PREFIX))
                else:
                    self.handler(payload)
            connection.disconnectFromServer()

    def _discard(self, connection: QLocalSocket) -> None:
        self.connections.discard(connection)
        connection.deleteLater()

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject
from PySide6.QtNetwork import QLocalServer, QLocalSocket

SERVER_NAME = "PourNotify-v1-notifications"


def send_to_running_instance(
    payload: str,
    timeout_ms: int = 750,
    server_name: str = SERVER_NAME,
) -> bool:
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
        parent: QObject | None = None,
        server_name: str = SERVER_NAME,
    ):
        super().__init__(parent)
        self.handler = handler
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
                self.handler(payload)
            connection.disconnectFromServer()

    def _discard(self, connection: QLocalSocket) -> None:
        self.connections.discard(connection)
        connection.deleteLater()

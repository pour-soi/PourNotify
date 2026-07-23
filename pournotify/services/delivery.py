from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Protocol

from PySide6.QtWidgets import QSystemTrayIcon

from ..models import Notification, Priority


class DesktopNotifier(Protocol):
    def send(self, notification: Notification, priority: Priority) -> None: ...


class TrayDesktopNotifier:
    def __init__(self, tray: QSystemTrayIcon):
        self.tray = tray

    def send(self, notification: Notification, priority: Priority) -> None:
        icon = QSystemTrayIcon.Critical if priority == Priority.CRITICAL else QSystemTrayIcon.Information
        self.tray.showMessage(notification.title, notification.message, icon, 8000)


class BarkClient:
    def send(self, server_url: str, device_key: str, notification: Notification, *,
             group: str, sound: str, time_sensitive: bool, silent: bool) -> None:
        if not server_url.startswith("https://"):
            raise ValueError("Bark server URL must use HTTPS.")
        endpoint = f"{server_url.rstrip('/')}/push"
        payload = {
            "device_key": device_key, "title": notification.title, "body": notification.message,
            "group": group, "sound": "silence" if silent else sound.lower(),
        }
        if time_sensitive:
            payload["level"] = "timeSensitive"
        request = urllib.request.Request(
            endpoint, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            if response.status >= 400:
                raise RuntimeError(f"Bark returned HTTP {response.status}")

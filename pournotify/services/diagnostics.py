from __future__ import annotations

import json
import os
import sys
import threading
from datetime import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from time import perf_counter

from .. import __version__
from ..config import app_data_dir
from .dispatcher import DispatchTrace

MAX_LOG_BYTES = 10 * 1024 * 1024


def diagnostics_log_path() -> Path:
    return app_data_dir() / "logs" / "notify-diagnostics.jsonl"


def _project_name(payload: object) -> str:
    if not isinstance(payload, dict):
        return ""
    explicit = payload.get("project")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    workspace = payload.get("cwd") or payload.get("workspace")
    if not isinstance(workspace, str) or not workspace.strip() or "\0" in workspace:
        return ""
    windows_path = PureWindowsPath(workspace)
    path = (
        windows_path
        if windows_path.drive or ("\\" in workspace and "/" not in workspace)
        else PurePosixPath(workspace)
    )
    return path.name


def _event_name(payload: object) -> object:
    if not isinstance(payload, dict):
        return ""
    for key in ("type", "event", "event_type"):
        if key in payload:
            return payload[key]
    return ""


def _safe_received_payload(received_payload: object) -> object:
    if not isinstance(received_payload, dict):
        return {"payload_type": type(received_payload).__name__}
    safe = {
        key: received_payload[key]
        for key in (
            "type",
            "event",
            "event_type",
            "thread-id",
            "turn-id",
            "cwd",
            "workspace",
            "client",
            "project",
        )
        if key in received_payload
    }
    messages = received_payload.get("input-messages")
    safe["input-message-count"] = len(messages) if isinstance(messages, list) else 0
    assistant_message = received_payload.get("last-assistant-message")
    safe["last-assistant-message-length"] = (
        len(assistant_message) if isinstance(assistant_message, str) else 0
    )
    return safe


def _safe_arguments(arguments: list[str]) -> list[str]:
    if not arguments:
        return []
    executable = arguments[0]
    windows_path = PureWindowsPath(executable)
    path = windows_path if windows_path.drive or "\\" in executable else PurePosixPath(executable)
    safe = [path.name]
    safe.extend(
        argument
        for argument in arguments[1:]
        if argument in {"--notify", "--observe-notify", "--background"}
    )
    return safe


class NotificationDiagnostics:
    def __init__(self, path: Path | None = None, max_bytes: int = MAX_LOG_BYTES):
        self.path = path or diagnostics_log_path()
        self.max_bytes = max(1, max_bytes)
        self._lock = threading.Lock()

    def record(
        self,
        received_payload: object,
        notify_source: str,
        trace: DispatchTrace,
        started_at: float,
        exception: str = "",
        arguments: list[str] | None = None,
    ) -> bool:
        payload = received_payload if isinstance(received_payload, dict) else {}
        raw_arguments = list(sys.argv if arguments is None else arguments)
        record = {
            "timestamp": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "event": _event_name(received_payload),
            "project": _project_name(received_payload),
            "workspace": payload.get("workspace", ""),
            "cwd": payload.get("cwd", ""),
            "pid": os.getpid(),
            "arguments": _safe_arguments(raw_arguments),
            "received_payload": _safe_received_payload(received_payload),
            "payload_redacted": True,
            "thread_id": payload.get("thread-id", ""),
            "turn_id": payload.get("turn-id", ""),
            "notify_source": notify_source,
            "dispatch_status": trace.dispatch_status,
            "history_attempted": trace.history_attempted,
            "desktop_attempted": trace.desktop_attempted,
            "sound_attempted": trace.sound_attempted,
            "bark_attempted": trace.bark_attempted,
            "desktop_result": trace.desktop_result,
            "sound_result": trace.sound_result,
            "bark_result": trace.bark_result,
            "history_result": trace.history_result,
            "http_status": trace.http_status,
            "bark_response": trace.bark_response,
            "duration_ms": round((perf_counter() - started_at) * 1000, 3),
            "exception": exception or trace.exception,
            "completion_classification": trace.completion_classification,
            "completion_reason": trace.completion_reason,
            "attention_state": trace.attention_state,
            "attention_reason": trace.attention_reason,
            "classification_reason": trace.classification_reason,
            "classifier_version": trace.classifier_version,
            "observer_version": trace.observer_version,
            "codex_thread_source": trace.codex_thread_source,
            "detected_lifecycle": trace.detected_lifecycle,
            "detection_reason": trace.detection_reason,
            "dedupe_result": trace.dedupe_result,
            "lifecycle_classification": trace.attention_state,
            "lifecycle_reason": trace.attention_reason or trace.classification_reason,
            "observation_only": trace.observation_only,
            "version": __version__,
        }
        try:
            line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
            encoded_size = len(line.encode("utf-8"))
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                if self.path.exists() and self.path.stat().st_size + encoded_size > self.max_bytes:
                    self._rotate()
                with self.path.open("a", encoding="utf-8", newline="") as stream:
                    stream.write(line)
            return True
        except Exception:  # noqa: BLE001 - diagnostics must never affect notification delivery
            return False

    def _rotate(self) -> None:
        second = self.path.with_name("notify-diagnostics.2.jsonl")
        first = self.path.with_name("notify-diagnostics.1.jsonl")
        if second.exists():
            second.unlink()
        if first.exists():
            first.replace(second)
        if self.path.exists():
            self.path.replace(first)

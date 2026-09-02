from __future__ import annotations

import json
import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

DEFAULT_MAX_READ_BYTES_PER_FILE = 512 * 1024
DEFAULT_MAX_READ_BYTES_PER_POLL = 2 * 1024 * 1024
DEFAULT_MAX_LINE_BYTES = 2 * 1024 * 1024
DEFAULT_MAX_METADATA_BYTES = 512 * 1024
DEFAULT_MAX_HYDRATION_BYTES = 512 * 1024
DEFAULT_ACTIVE_FILE_MAX_AGE_SECONDS = 24 * 60 * 60
OBSERVER_VERSION = "3"
USER_THREAD_SOURCES = {"user", "agent_created_thread"}


def resolve_codex_thread_source(sessions_root: Path, thread_id: str) -> str:
    """Read only the matching rollout's session metadata; never scan turn content."""
    if not re.fullmatch(r"[A-Za-z0-9-]{8,128}", thread_id):
        return ""
    root = Path(sessions_root)
    try:
        paths = root.rglob(f"*{thread_id}*.jsonl")
        for path in paths:
            with path.open("rb") as stream:
                first_line = stream.readline(DEFAULT_MAX_METADATA_BYTES + 1)
            if not first_line or len(first_line) > DEFAULT_MAX_METADATA_BYTES:
                continue
            record = json.loads(first_line.decode("utf-8"))
            payload = record.get("payload") if isinstance(record, dict) else None
            if (
                not isinstance(record, dict)
                or record.get("type") != "session_meta"
                or not isinstance(payload, dict)
                or payload.get("id") != thread_id
            ):
                continue
            thread_source = payload.get("thread_source")
            return thread_source if isinstance(thread_source, str) else ""
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return ""
    return ""


@dataclass(slots=True)
class ObserverMetrics:
    polls: int = 0
    baselines: int = 0
    files_baselined: int = 0
    files_discovered: int = 0
    files_scanned: int = 0
    files_changed: int = 0
    bytes_read: int = 0
    baseline_bytes_read: int = 0
    hydration_bytes_read: int = 0
    active_turns_hydrated: int = 0
    lines_read: int = 0
    malformed_lines: int = 0
    schema_rejections: int = 0
    oversized_lines: int = 0
    read_errors: int = 0
    source_errors: int = 0
    file_resets: int = 0
    candidates_detected: int = 0
    candidates_emitted: int = 0
    callback_errors: int = 0


@dataclass(slots=True)
class _TurnState:
    turn_id: str
    started: bool = False
    cwd: str = ""
    input_messages: list[str] = field(default_factory=list)
    final_message: str = ""


@dataclass(slots=True)
class _FileState:
    offset: int
    identity: tuple[int, int]
    partial: bytes = b""
    discard_until_newline: bool = False
    thread_id: str = ""
    thread_source: str = ""
    cwd: str = ""
    active_turn_id: str = ""
    require_post_baseline_timestamp: bool = False
    turns: dict[str, _TurnState] = field(default_factory=dict)

    def reset_runtime_state(self) -> None:
        self.partial = b""
        self.discard_until_newline = False
        self.active_turn_id = ""
        self.turns.clear()


class CodexRolloutObserver:
    """Read newly appended Codex rollout records without modifying Codex state."""

    def __init__(
        self,
        sessions_root: Path,
        emit: Callable[[dict[str, Any]], None],
        *,
        enabled: bool = False,
        max_read_bytes_per_file: int = DEFAULT_MAX_READ_BYTES_PER_FILE,
        max_read_bytes_per_poll: int = DEFAULT_MAX_READ_BYTES_PER_POLL,
        max_line_bytes: int = DEFAULT_MAX_LINE_BYTES,
        max_metadata_bytes: int = DEFAULT_MAX_METADATA_BYTES,
        max_hydration_bytes: int = DEFAULT_MAX_HYDRATION_BYTES,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if max_read_bytes_per_file < 1:
            raise ValueError("max_read_bytes_per_file must be positive")
        if max_read_bytes_per_poll < 1:
            raise ValueError("max_read_bytes_per_poll must be positive")
        if max_line_bytes < 1:
            raise ValueError("max_line_bytes must be positive")
        if max_metadata_bytes < 1:
            raise ValueError("max_metadata_bytes must be positive")
        if max_hydration_bytes < 1:
            raise ValueError("max_hydration_bytes must be positive")

        self.sessions_root = Path(sessions_root)
        self._emit = emit
        self._enabled = False
        self._baseline_ready = False
        self._states: dict[Path, _FileState] = {}
        self._metrics = ObserverMetrics()
        self._max_read_bytes_per_file = max_read_bytes_per_file
        self._max_read_bytes_per_poll = max_read_bytes_per_poll
        self._max_line_bytes = max_line_bytes
        self._max_metadata_bytes = max_metadata_bytes
        self._max_hydration_bytes = max_hydration_bytes
        self._clock = clock or time.time
        self._baseline_started_at = 0.0
        self._poll_cursor = 0
        if enabled:
            self.set_enabled(True)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def metrics_snapshot(self) -> ObserverMetrics:
        return replace(self._metrics)

    def set_enabled(self, enabled: bool) -> None:
        if enabled == self._enabled:
            return
        self._enabled = enabled
        self._states.clear()
        self._baseline_ready = False
        self._poll_cursor = 0
        if enabled:
            self._baseline_started_at = self._clock()
            self._establish_baseline()

    def poll_once(self) -> None:
        """Scan once; callers choose a conservative scheduling interval."""
        if not self._enabled:
            return
        self._metrics.polls += 1
        if not self._baseline_ready:
            self._establish_baseline()
            return

        paths = self._discover_poll_paths()
        if paths is None:
            return

        remaining_budget = self._max_read_bytes_per_poll
        if paths:
            start = self._poll_cursor % len(paths)
            paths = paths[start:] + paths[:start]
        visited = 0
        for path in paths:
            if remaining_budget <= 0:
                break
            visited += 1
            try:
                stat = path.stat()
            except FileNotFoundError:
                self._states.pop(path, None)
                continue
            except OSError:
                self._metrics.read_errors += 1
                continue

            identity = (stat.st_dev, stat.st_ino)
            state = self._states.get(path)
            if state is None:
                state = _FileState(
                    offset=0,
                    identity=identity,
                    require_post_baseline_timestamp=True,
                )
                self._states[path] = state
                self._metrics.files_discovered += 1
            elif identity != state.identity or stat.st_size < state.offset:
                self._reset_file(path, state, stat.st_size, identity)
                continue

            self._metrics.files_scanned += 1
            available = stat.st_size - state.offset
            if available <= 0:
                continue
            read_size = min(
                available,
                remaining_budget,
                self._max_read_bytes_per_file,
            )
            try:
                with path.open("rb") as stream:
                    stream.seek(state.offset)
                    data = stream.read(read_size)
            except OSError:
                self._metrics.read_errors += 1
                continue
            if not data:
                continue

            state.offset += len(data)
            remaining_budget -= len(data)
            self._metrics.files_changed += 1
            self._metrics.bytes_read += len(data)
            self._consume_bytes(state, data)
        if paths:
            self._poll_cursor = (self._poll_cursor + max(1, visited)) % len(paths)

    def _establish_baseline(self) -> None:
        paths = self._discover_paths()
        if paths is None:
            return

        states: dict[Path, _FileState] = {}
        deferred_candidates: list[dict[str, Any]] = []
        baseline_failed = False
        for path in paths:
            try:
                stat = path.stat()
            except OSError:
                self._metrics.read_errors += 1
                baseline_failed = True
                continue
            state = _FileState(
                offset=stat.st_size,
                identity=(stat.st_dev, stat.st_ino),
            )
            self._read_session_metadata(path, state)
            if stat.st_mtime >= (
                self._baseline_started_at - DEFAULT_ACTIVE_FILE_MAX_AGE_SECONDS
            ):
                state.require_post_baseline_timestamp = True
                self._hydrate_active_turn(
                    path,
                    state,
                    stat.st_size,
                    candidate_sink=deferred_candidates.append,
                )
                state.require_post_baseline_timestamp = False
            states[path] = state

        if baseline_failed:
            return

        self._states = states
        self._baseline_ready = True
        self._metrics.baselines += 1
        self._metrics.files_baselined += len(states)
        for candidate in deferred_candidates:
            self._emit_candidate(candidate)

    def _discover_paths(self) -> list[Path] | None:
        try:
            if not self.sessions_root.is_dir():
                self._metrics.source_errors += 1
                return None
            return sorted(self.sessions_root.rglob("rollout-*.jsonl"))
        except OSError:
            self._metrics.source_errors += 1
            return None

    def _discover_poll_paths(self) -> list[Path] | None:
        try:
            if not self.sessions_root.is_dir():
                self._metrics.source_errors += 1
                return None
            paths = set(self._states)
            now = self._clock()
            utc_now = datetime.fromtimestamp(now, UTC)
            dates = {utc_now.date(), utc_now.astimezone().date()}
            dates |= {
                day + delta
                for day in dates
                for delta in (timedelta(days=-1), timedelta(days=1))
            }
            for day in dates:
                directory = self.sessions_root / day.strftime("%Y/%m/%d")
                if directory.is_dir():
                    paths.update(directory.glob("rollout-*.jsonl"))
            return sorted(paths)
        except (OSError, ValueError, OverflowError):
            self._metrics.source_errors += 1
            return None

    def _reset_file(
        self,
        path: Path,
        state: _FileState,
        size: int,
        identity: tuple[int, int],
    ) -> None:
        state.offset = size
        state.identity = identity
        state.thread_id = ""
        state.thread_source = ""
        state.cwd = ""
        state.reset_runtime_state()
        self._read_session_metadata(path, state)
        self._metrics.file_resets += 1

    def _read_session_metadata(self, path: Path, state: _FileState) -> None:
        try:
            with path.open("rb") as stream:
                data = stream.readline(self._max_metadata_bytes + 1)
        except OSError:
            self._metrics.read_errors += 1
            return
        self._metrics.baseline_bytes_read += len(data)
        newline = data.find(b"\n")
        if newline < 0:
            if len(data) > self._max_metadata_bytes:
                self._metrics.oversized_lines += 1
            return
        self._process_line(state, data[:newline].rstrip(b"\r"), metadata_only=True)

    def _hydrate_active_turn(
        self,
        path: Path,
        state: _FileState,
        size: int,
        *,
        candidate_sink: Callable[[dict[str, Any]], None],
    ) -> None:
        start = max(0, size - self._max_hydration_bytes)
        try:
            with path.open("rb") as stream:
                stream.seek(start)
                data = stream.read(size - start)
        except OSError:
            self._metrics.read_errors += 1
            return
        self._metrics.hydration_bytes_read += len(data)
        if start:
            newline = data.find(b"\n")
            if newline < 0:
                return
            data = data[newline + 1 :]
        self._consume_bytes(state, data, candidate_sink=candidate_sink)
        self._metrics.active_turns_hydrated += sum(
            turn.started for turn in state.turns.values()
        )

    def _consume_bytes(
        self,
        state: _FileState,
        data: bytes,
        *,
        emit_candidates: bool = True,
        candidate_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        buffer = state.partial + data
        state.partial = b""
        while buffer:
            if state.discard_until_newline:
                newline = buffer.find(b"\n")
                if newline < 0:
                    return
                buffer = buffer[newline + 1 :]
                state.discard_until_newline = False
                continue

            newline = buffer.find(b"\n")
            if newline < 0:
                if len(buffer) > self._max_line_bytes:
                    self._metrics.oversized_lines += 1
                    state.discard_until_newline = True
                else:
                    state.partial = buffer
                return

            line = buffer[:newline].rstrip(b"\r")
            buffer = buffer[newline + 1 :]
            if len(line) > self._max_line_bytes:
                self._metrics.oversized_lines += 1
                continue
            self._process_line(
                state,
                line,
                emit_candidates=emit_candidates,
                candidate_sink=candidate_sink,
            )

    def _process_line(
        self,
        state: _FileState,
        line: bytes,
        *,
        metadata_only: bool = False,
        emit_candidates: bool = True,
        candidate_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        if not line:
            return
        self._metrics.lines_read += 1
        try:
            record = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._metrics.malformed_lines += 1
            return
        if not isinstance(record, dict):
            self._metrics.schema_rejections += 1
            return

        record_type = record.get("type")
        payload = record.get("payload")
        if not isinstance(record_type, str) or not isinstance(payload, dict):
            self._metrics.schema_rejections += 1
            return

        if record_type == "session_meta":
            self._apply_session_metadata(state, payload)
            return
        if metadata_only:
            return
        if record_type == "turn_context":
            self._apply_turn_context(state, payload)
            return
        if record_type == "response_item":
            self._apply_response_item(state, payload)
            return
        if record_type != "event_msg":
            return

        event_type = payload.get("type")
        if event_type == "task_started":
            self._apply_task_started(state, payload)
        elif event_type == "item_completed":
            self._apply_item_completed(state, payload)
        elif event_type == "user_message":
            self._apply_user_message(state, payload)
        elif event_type == "agent_message":
            self._apply_agent_message(state, payload)
        elif event_type == "task_complete":
            self._apply_task_complete(
                state,
                payload,
                emit_candidate=emit_candidates,
                candidate_sink=candidate_sink,
            )
        elif event_type == "turn_aborted":
            self._apply_turn_aborted(state, payload)

    def _apply_session_metadata(self, state: _FileState, payload: dict[str, Any]) -> None:
        thread_id = payload.get("id")
        thread_source = payload.get("thread_source")
        cwd = payload.get("cwd")
        if not isinstance(thread_id, str) or not thread_id.strip():
            self._metrics.schema_rejections += 1
            return
        if not isinstance(thread_source, str):
            self._metrics.schema_rejections += 1
            return
        if not isinstance(cwd, str) or not cwd.strip() or "\0" in cwd:
            self._metrics.schema_rejections += 1
            return
        state.thread_id = thread_id.strip()
        state.thread_source = thread_source
        state.cwd = cwd

    def _apply_task_started(self, state: _FileState, payload: dict[str, Any]) -> None:
        turn_id = payload.get("turn_id")
        if not isinstance(turn_id, str) or not turn_id.strip():
            self._metrics.schema_rejections += 1
            return
        turn_id = turn_id.strip()
        state.active_turn_id = turn_id
        state.turns[turn_id] = _TurnState(turn_id=turn_id, started=True, cwd=state.cwd)

    def _apply_turn_context(self, state: _FileState, payload: dict[str, Any]) -> None:
        turn_id = payload.get("turn_id")
        cwd = payload.get("cwd")
        if not isinstance(turn_id, str) or not turn_id.strip():
            self._metrics.schema_rejections += 1
            return
        turn_id = turn_id.strip()
        turn = state.turns.get(turn_id)
        if turn is None:
            turn = _TurnState(turn_id=turn_id)
            state.turns[turn_id] = turn
        if isinstance(cwd, str) and cwd.strip() and "\0" not in cwd:
            turn.cwd = cwd
        state.active_turn_id = turn_id

    def _apply_item_completed(self, state: _FileState, payload: dict[str, Any]) -> None:
        thread_id = payload.get("thread_id")
        turn_id = payload.get("turn_id")
        if thread_id != state.thread_id or not isinstance(turn_id, str):
            return
        turn = state.turns.get(turn_id)
        if turn is None:
            return

        item = payload.get("item")
        if not isinstance(item, dict):
            self._metrics.schema_rejections += 1
            return
        item_type = item.get("type")
        if item_type == "FunctionCallOutput":
            message = self._codex_app_delegated_input(item)
            if message and message not in turn.input_messages:
                turn.input_messages.append(message)
            return
        if item_type == "UserMessage":
            message = self._item_text(item, "text")
            if not message:
                self._metrics.schema_rejections += 1
                return
            turn.input_messages.append(message)
            return
        if item_type != "AgentMessage" or item.get("phase") != "final_answer":
            return

        message = self._item_text(item, "Text")
        if not message:
            self._metrics.schema_rejections += 1
            return
        turn.final_message = message

    def _apply_response_item(self, state: _FileState, payload: dict[str, Any]) -> None:
        if payload.get("type") == "function_call_output":
            metadata = payload.get("internal_chat_message_metadata_passthrough")
            turn = state.turns.get(state.active_turn_id)
            if (
                turn is not None
                and isinstance(metadata, dict)
                and metadata.get("turn_id") == state.active_turn_id
            ):
                message = self._codex_app_delegated_input(payload)
                if message and message not in turn.input_messages:
                    turn.input_messages.append(message)
            return
        if payload.get("type") != "message":
            return
        turn = state.turns.get(state.active_turn_id)
        if turn is None:
            return

        role = payload.get("role")
        if role == "user":
            message = self._item_text(payload, "input_text")
            if not message:
                self._metrics.schema_rejections += 1
                return
            turn.input_messages.append(message)
            return
        if role != "assistant" or payload.get("phase") != "final_answer":
            return

        message = self._item_text(payload, "output_text")
        if not message:
            self._metrics.schema_rejections += 1
            return
        turn.final_message = message

    @staticmethod
    def _codex_app_delegated_input(payload: dict[str, Any]) -> str:
        if (
            payload.get("namespace") != "codex_app"
            or payload.get("name") != "send_message_to_thread"
        ):
            return ""
        output = payload.get("output")
        if not isinstance(output, str) or not output.strip():
            return ""
        try:
            root = ET.fromstring(output)
        except ET.ParseError:
            return ""
        children = list(root)
        if (
            root.tag != "codex_delegation"
            or [child.tag for child in children] != ["source_thread_id", "input"]
            or any(list(child) for child in children)
        ):
            return ""
        source_thread_id = children[0].text
        delegated_input = children[1].text
        if (
            not isinstance(source_thread_id, str)
            or not source_thread_id.strip()
            or not isinstance(delegated_input, str)
            or not delegated_input.strip()
        ):
            return ""
        return delegated_input.strip()

    @staticmethod
    def _item_text(item: dict[str, Any], block_type: str) -> str:
        content = item.get("content")
        if not isinstance(content, list):
            return ""
        texts = []
        for block in content:
            if not isinstance(block, dict) or block.get("type") != block_type:
                continue
            text = block.get("text")
            if isinstance(text, str) and text.strip():
                texts.append(text)
        return "\n".join(texts)

    def _apply_user_message(self, state: _FileState, payload: dict[str, Any]) -> None:
        turn = state.turns.get(state.active_turn_id)
        message = payload.get("message")
        if turn is None or not isinstance(message, str) or not message.strip():
            self._metrics.schema_rejections += 1
            return
        turn.input_messages.append(message)

    def _apply_agent_message(self, state: _FileState, payload: dict[str, Any]) -> None:
        turn = state.turns.get(state.active_turn_id)
        phase = payload.get("phase")
        message = payload.get("message")
        if turn is None:
            self._metrics.schema_rejections += 1
            return
        if phase == "final_answer" and isinstance(message, str) and message.strip():
            turn.final_message = message

    def _apply_task_complete(
        self,
        state: _FileState,
        payload: dict[str, Any],
        *,
        emit_candidate: bool,
        candidate_sink: Callable[[dict[str, Any]], None] | None,
    ) -> None:
        turn_id = payload.get("turn_id")
        if not isinstance(turn_id, str) or not turn_id.strip():
            self._metrics.schema_rejections += 1
            return
        turn_id = turn_id.strip()
        turn = state.turns.pop(turn_id, None)
        if state.active_turn_id == turn_id:
            state.active_turn_id = ""
        if turn is None:
            self._metrics.schema_rejections += 1
            return

        last_message = payload.get("last_agent_message")
        cwd = turn.cwd or state.cwd
        if (
            state.require_post_baseline_timestamp
            and self._completion_timestamp(payload.get("completed_at"))
            < self._baseline_started_at
        ):
            return
        if (
            state.thread_source not in USER_THREAD_SOURCES
            or not state.thread_id
            or not turn.started
            or not isinstance(cwd, str)
            or not cwd.strip()
            or "\0" in cwd
            or not turn.input_messages
            or not all(message.strip() for message in turn.input_messages)
            or not isinstance(last_message, str)
            or not last_message.strip()
            or not turn.final_message
            or turn.final_message != last_message
        ):
            self._metrics.schema_rejections += 1
            return

        candidate = {
            "type": "agent-turn-complete",
            "thread-id": state.thread_id,
            "turn-id": turn_id,
            "cwd": cwd,
            "input-messages": list(turn.input_messages),
            "last-assistant-message": last_message,
        }
        if not emit_candidate:
            return
        if candidate_sink is not None:
            candidate_sink(candidate)
            return
        self._emit_candidate(candidate)

    def _emit_candidate(self, candidate: dict[str, Any]) -> None:
        self._metrics.candidates_detected += 1
        try:
            self._emit(candidate)
        except Exception:  # noqa: BLE001 - observer failures must not affect normal notify
            self._metrics.callback_errors += 1
            return
        self._metrics.candidates_emitted += 1

    @staticmethod
    def _completion_timestamp(value: Any) -> float:
        if isinstance(value, bool):
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        if not isinstance(value, str) or not value.strip():
            return 0.0
        try:
            return datetime.fromisoformat(value).timestamp()
        except ValueError:
            return 0.0

    def _apply_turn_aborted(self, state: _FileState, payload: dict[str, Any]) -> None:
        turn_id = payload.get("turn_id")
        if not isinstance(turn_id, str) or not turn_id.strip():
            self._metrics.schema_rejections += 1
            return
        turn_id = turn_id.strip()
        state.turns.pop(turn_id, None)
        if state.active_turn_id == turn_id:
            state.active_turn_id = ""

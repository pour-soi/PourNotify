import json
from types import SimpleNamespace

from pournotify.config import AppConfig
from pournotify.main import dispatch_codex_payload
from pournotify.models import Category, Notification
from pournotify.services.delivery import BarkClient, BarkDeliveryResult
from pournotify.services.diagnostics import NotificationDiagnostics
from pournotify.services.dispatcher import DispatchTrace, NotificationDispatcher


class SuccessfulDispatcher:
    def dispatch(self, notification, trace):
        trace.desktop_attempted = True
        trace.desktop_result = "attempted_no_exception"
        trace.sound_attempted = True
        trace.sound_result = "attempted_no_exception"
        trace.bark_attempted = True
        trace.bark_result = "success"
        trace.http_status = 200
        trace.bark_response = '{"code":200}'
        trace.history_attempted = True
        trace.history_result = "success"
        return SimpleNamespace(status="attempted")


class Recorder:
    def __init__(self, bark_result=None):
        self.items = []
        self.bark_result = bark_result

    def send(self, *args, **kwargs):
        self.items.append((args, kwargs))
        return self.bark_result

    def add(self, *args, **kwargs):
        self.items.append((args, kwargs))

    def play(self, *args, **kwargs):
        self.items.append((args, kwargs))

    def has_recent_duplicate(self, *args, **kwargs):
        return False

    def count_delivered_since(self, *args, **kwargs):
        return 0


def read_lines(path):
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]


def test_supported_event_records_complete_delivery_diagnostics(tmp_path):
    path = tmp_path / "notify-diagnostics.jsonl"
    diagnostics = NotificationDiagnostics(path)
    payload = {
        "type": "agent-turn-complete",
        "cwd": r"F:\work\PourCase",
        "workspace": r"F:\work\PourCase",
        "thread-id": "diagnostic-thread",
        "turn-id": "diagnostic-turn",
        "input-messages": ["Inspect the notification path and report the result."],
        "last-assistant-message": (
            "The notification path reached each configured channel and recorded the expected "
            "diagnostic result."
        ),
    }

    assert dispatch_codex_payload(
        SimpleNamespace(dispatcher=SuccessfulDispatcher()),
        json.dumps(payload),
        diagnostics,
        notify_source="ipc",
    )

    record = read_lines(path)[0]
    assert record["received_payload"] == {
        "type": "agent-turn-complete",
        "thread-id": "diagnostic-thread",
        "turn-id": "diagnostic-turn",
        "cwd": r"F:\work\PourCase",
        "workspace": r"F:\work\PourCase",
        "input-message-count": 1,
        "last-assistant-message-length": len(payload["last-assistant-message"]),
    }
    assert record["event"] == "agent-turn-complete"
    assert record["project"] == "PourCase"
    assert record["notify_source"] == "ipc"
    assert record["dispatch_status"] == "attempted"
    assert record["desktop_attempted"] is True
    assert record["sound_attempted"] is True
    assert record["bark_attempted"] is True
    assert record["history_attempted"] is True
    assert record["desktop_result"] == "attempted_no_exception"
    assert record["sound_result"] == "attempted_no_exception"
    assert record["bark_result"] == "success"
    assert record["history_result"] == "success"
    assert record["http_status"] == 200
    assert record["bark_response"] == '{"code":200}'
    assert record["completion_classification"] == "high_confidence_completion"
    assert record["completion_reason"] == "substantive_user_facing_result"
    assert record["classifier_version"]
    assert record["lifecycle_classification"] == "high_confidence_completion"
    assert record["lifecycle_reason"] == "substantive_user_facing_result"
    assert record["observation_only"] is False
    assert record["duration_ms"] >= 0
    assert record["version"]


def test_unsupported_approval_payload_is_logged_without_filtering(tmp_path):
    path = tmp_path / "notify-diagnostics.jsonl"
    diagnostics = NotificationDiagnostics(path)
    payload = {
        "event": "approval",
        "event_type": "approval-required",
        "details": {
            "type": "tool-call",
            "related_event": "agent-turn-complete",
            "arguments": {"command": "example"},
        },
        "cwd": r"F:\work\PourNotify",
    }

    assert not dispatch_codex_payload(
        SimpleNamespace(dispatcher=SuccessfulDispatcher()),
        json.dumps(payload),
        diagnostics,
    )

    record = read_lines(path)[0]
    assert record["received_payload"] == {
        "event": "approval",
        "event_type": "approval-required",
        "cwd": r"F:\work\PourNotify",
        "input-message-count": 0,
        "last-assistant-message-length": 0,
    }
    assert record["event"] == "approval"
    assert record["project"] == "PourNotify"
    assert record["dispatch_status"] == "unsupported_event"
    assert record["desktop_attempted"] is False
    assert record["bark_attempted"] is False
    assert record["history_attempted"] is False
    assert record["desktop_result"] == "not_attempted"
    assert record["bark_result"] == "not_attempted"
    assert record["history_result"] == "not_attempted"


def test_diagnostics_rotates_to_two_backups(tmp_path):
    path = tmp_path / "notify-diagnostics.jsonl"
    diagnostics = NotificationDiagnostics(path, max_bytes=1)

    for index in range(4):
        diagnostics.record(
            {"event": f"event-{index}"},
            "test",
            DispatchTrace(),
            0,
            arguments=[],
        )

    assert path.is_file()
    assert path.with_name("notify-diagnostics.1.jsonl").is_file()
    assert path.with_name("notify-diagnostics.2.jsonl").is_file()
    assert not path.with_name("notify-diagnostics.3.jsonl").exists()
    assert read_lines(path)[0]["received_payload"] == {
        "event": "event-3",
        "input-message-count": 0,
        "last-assistant-message-length": 0,
    }


def test_diagnostics_redacts_payload_bearing_command_line_arguments(tmp_path):
    path = tmp_path / "notify-diagnostics.jsonl"
    diagnostics = NotificationDiagnostics(path)

    diagnostics.record(
        {"type": "agent-turn-complete", "input-messages": ["PRIVATE-PROMPT"]},
        "command_line",
        DispatchTrace(),
        0,
        arguments=["C:\\Program Files\\PourNotify.exe", "--notify", "PRIVATE-ARGUMENT"],
    )

    serialized = path.read_text(encoding="utf-8")
    record = read_lines(path)[0]
    assert record["arguments"] == ["PourNotify.exe", "--notify"]
    assert "PRIVATE-PROMPT" not in serialized
    assert "PRIVATE-ARGUMENT" not in serialized


def test_dispatcher_populates_channel_trace_without_changing_status():
    config = AppConfig(bark_enabled=True, bark_device_key="configured")
    config.categories[Category.TASK_COMPLETED.value].bark = True
    history, desktop, sounds = Recorder(), Recorder(), Recorder()
    bark = Recorder(BarkDeliveryResult(200, '{"code":200}'))
    dispatcher = NotificationDispatcher(config, history, desktop, sounds, bark)
    trace = DispatchTrace()

    result = dispatcher.dispatch(
        Notification(Category.TASK_COMPLETED, "Complete", "Done"),
        trace=trace,
    )

    assert result.status == "attempted"
    assert trace.desktop_attempted is True
    assert trace.desktop_result == "attempted_no_exception"
    assert trace.sound_attempted is True
    assert trace.sound_result == "attempted_no_exception"
    assert trace.bark_attempted is True
    assert trace.bark_result == "success"
    assert trace.http_status == 200
    assert trace.bark_response == '{"code":200}'
    assert trace.history_attempted is True
    assert trace.history_result == "success"


def test_suppressed_completion_records_safe_diagnostics_without_dispatch(tmp_path):
    class FailingDispatcher:
        @staticmethod
        def dispatch(*args, **kwargs):
            raise AssertionError("suppressed events must not reach the dispatcher")

    path = tmp_path / "notify-diagnostics.jsonl"
    diagnostics = NotificationDiagnostics(path)
    private_prompt = (
        "You write the one-line activity update displayed beneath an existing Codex task "
        "title. Fill the structured summary field. PRIVATE-PROMPT"
    )
    private_result = '{"summary":"PRIVATE-RESULT completed"}'
    payload = {
        "type": "agent-turn-complete",
        "thread-id": "internal-thread",
        "turn-id": "internal-turn",
        "cwd": r"F:\work\PourNotify",
        "client": "Codex Desktop",
        "input-messages": [private_prompt],
        "last-assistant-message": private_result,
    }

    assert not dispatch_codex_payload(
        SimpleNamespace(dispatcher=FailingDispatcher()),
        json.dumps(payload),
        diagnostics,
    )

    serialized = path.read_text(encoding="utf-8")
    record = read_lines(path)[0]
    assert record["dispatch_status"] == "completion_suppressed"
    assert record["completion_classification"] == "suppressed_internal"
    assert record["completion_reason"] == "activity_summary_turn"
    assert record["thread_id"] == "internal-thread"
    assert record["turn_id"] == "internal-turn"
    assert record["desktop_attempted"] is False
    assert record["sound_attempted"] is False
    assert record["bark_attempted"] is False
    assert record["history_attempted"] is False
    assert "PRIVATE-PROMPT" not in serialized
    assert "PRIVATE-RESULT" not in serialized


def test_observation_only_classifies_high_confidence_without_dispatch(tmp_path):
    class FailingDispatcher:
        @staticmethod
        def dispatch(*args, **kwargs):
            raise AssertionError("observation mode must not reach the dispatcher")

    path = tmp_path / "notify-diagnostics.jsonl"
    diagnostics = NotificationDiagnostics(path)
    payload = {
        "type": "agent-turn-complete",
        "thread-id": "observation-thread",
        "turn-id": "observation-turn",
        "input-messages": ["Inspect the project and report the result."],
        "last-assistant-message": (
            "The inspection found the requested service boundary and preserved unrelated "
            "project behavior."
        ),
    }

    assert not dispatch_codex_payload(
        SimpleNamespace(dispatcher=FailingDispatcher()),
        json.dumps(payload),
        diagnostics,
        observation_only=True,
    )

    record = read_lines(path)[0]
    assert record["dispatch_status"] == "observation_only"
    assert record["completion_classification"] == "high_confidence_completion"
    assert record["observation_only"] is True
    assert record["desktop_attempted"] is False
    assert record["sound_attempted"] is False
    assert record["bark_attempted"] is False
    assert record["history_attempted"] is False


def test_bark_client_captures_response_and_redacts_device_key(monkeypatch):
    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        @staticmethod
        def read():
            return b'{"code":200,"echo":"secret-key"}'

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: Response())

    result = BarkClient().send(
        "https://api.day.app",
        "secret-key",
        Notification(Category.TASK_COMPLETED, "Complete", "Done"),
        group="PourNotify",
        sound="default",
        time_sensitive=False,
        silent=False,
    )

    assert result.http_status == 200
    assert result.response == '{"code":200,"echo":"[REDACTED]"}'

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from pournotify.config import AppConfig
from pournotify.main import dispatch_codex_payload
from pournotify.models import Category, Notification, Priority
from pournotify.services.codex import parse_codex_event
from pournotify.services.codex_observer import OBSERVER_VERSION
from pournotify.services.delivery import BarkDeliveryResult
from pournotify.services.diagnostics import NotificationDiagnostics
from pournotify.services.dispatcher import NotificationDispatcher
from pournotify.services.history import HistoryStore
from pournotify.services.lifecycle_ledger import CodexLifecycleLedger


class Recorder:
    def __init__(self, result=None):
        self.items = []
        self.result = result

    def send(self, *args, **kwargs):
        self.items.append((args, kwargs))
        return self.result

    def add(self, *args, **kwargs):
        self.items.append((args, kwargs))

    def merge_last(self, *args, **kwargs):
        self.items.append((args, kwargs))

    def play(self, *args, **kwargs):
        self.items.append((args, kwargs))

    def has_recent_duplicate(self, *args, **kwargs):
        return False

    def count_delivered_since(self, *args, **kwargs):
        return 0


def dispatcher(config, now):
    history, desktop, sounds, bark = Recorder(), Recorder(), Recorder(), Recorder()
    service = NotificationDispatcher(config, history, desktop, sounds, bark, lambda: now)
    return service, history, desktop, sounds, bark


def test_each_category_has_independent_settings():
    config = AppConfig()
    assert set(config.categories) == {category.value for category in Category}
    first = config.categories[Category.TASK_COMPLETED.value]
    second = config.categories[Category.LOW_QUOTA.value]
    first.desktop = False
    assert second.desktop is True


def test_disabled_category_stops_complete_pipeline():
    config = AppConfig()
    config.categories[Category.TASK_COMPLETED.value].enabled = False
    service, history, desktop, sounds, bark = dispatcher(
        config, datetime(2026, 7, 23, 12, tzinfo=UTC)
    )
    result = service.dispatch(Notification(Category.TASK_COMPLETED, "Done", "Complete"))
    assert result.status == "disabled"
    assert not any((history.items, desktop.items, sounds.items, bark.items))


def test_quiet_hours_keep_desktop_but_mute_sound():
    config = AppConfig(quiet_hours_enabled=True, quiet_start="22:00", quiet_end="08:00")
    setting = config.categories[Category.TASK_COMPLETED.value]
    setting.priority = Priority.NORMAL
    service, history, desktop, sounds, _ = dispatcher(
        config, datetime(2026, 7, 23, 23, tzinfo=UTC)
    )
    service.dispatch(Notification(Category.TASK_COMPLETED, "Done", "Complete"))
    assert len(desktop.items) == 1
    assert sounds.items == []
    assert len(history.items) == 1


def test_critical_can_bypass_quiet_hours():
    config = AppConfig(quiet_hours_enabled=True, quiet_start="22:00", quiet_end="08:00")
    setting = config.categories[Category.TASK_FAILED.value]
    setting.sound = True
    setting.priority = Priority.CRITICAL
    service, _, _, sounds, _ = dispatcher(
        config, datetime(2026, 7, 23, 23, tzinfo=UTC)
    )
    service.dispatch(Notification(Category.TASK_FAILED, "Failed", "Failure"))
    assert len(sounds.items) == 1


def test_duplicate_merge_and_rate_limit():
    config = AppConfig(cooldown_seconds=30, max_per_minute=2, merge_duplicates=True)
    service, *_ = dispatcher(config, datetime(2026, 7, 23, 12, tzinfo=UTC))
    notice = Notification(Category.SYSTEM_EVENTS, "Same", "Same")
    assert service.dispatch(notice).delivered
    assert service.dispatch(notice).status == "merged_duplicate"
    assert service.dispatch(Notification(Category.SYSTEM_EVENTS, "Other", "One")).delivered
    assert service.dispatch(Notification(Category.SYSTEM_EVENTS, "Third", "Two")).status == "rate_limited"


def test_delivery_is_truncated_but_history_preserves_original():
    config = AppConfig()
    service, history, desktop, _, _ = dispatcher(
        config, datetime(2026, 7, 23, 12, tzinfo=UTC)
    )
    original = "x" * 800
    service.dispatch(Notification(Category.TASK_COMPLETED, "Long", original))
    delivered = desktop.items[0][0][0]
    recorded = history.items[0][0][0]
    assert len(delivered.message) == 500
    assert recorded.message == original
    assert history.items[0][0][1] == "attempted"
    assert history.items[0][0][2] == Priority.NORMAL


def test_persisted_deduplication_survives_dispatcher_restart(tmp_path):
    config = AppConfig(cooldown_seconds=30, merge_duplicates=True)
    history = HistoryStore(tmp_path / "history.json")
    now = datetime.now(UTC).replace(microsecond=0)
    first = NotificationDispatcher(
        config, history, Recorder(), Recorder(), Recorder(), lambda: now
    )
    second = NotificationDispatcher(
        config, history, Recorder(), Recorder(), Recorder(), lambda: now
    )
    notice = Notification(
        Category.TASK_COMPLETED, "Codex Task Completed", "Done",
        deduplication_id="same-turn",
    )
    assert first.dispatch(notice).status == "attempted"
    assert second.dispatch(notice).status == "merged_duplicate"
    entries = history.read()
    assert len(entries) == 1
    assert entries[0]["count"] == 2


def test_input_required_then_completion_delivers_one_of_each_lifecycle_notice(tmp_path):
    config = AppConfig(bark_enabled=True, bark_device_key="configured")
    for category in (Category.INPUT_REQUIRED, Category.TASK_COMPLETED):
        config.categories[category.value].bark = True
    history = HistoryStore(tmp_path / "history.json")
    desktop, sounds = Recorder(), Recorder()
    bark = Recorder(BarkDeliveryResult(200, '{"code":200}'))
    service = NotificationDispatcher(config, history, desktop, sounds, bark)
    base = {
        "type": "agent-turn-complete",
        "thread-id": "thread-lifecycle",
        "cwd": r"F:\work\PourDeploy",
        "input-messages": ["Complete the deployment preparation."],
    }
    waiting = parse_codex_event({
        **base,
        "turn-id": "turn-waiting",
        "last-assistant-message": (
            "I need your target environment before I can continue with the deployment."
        ),
    })
    completed = parse_codex_event({
        **base,
        "turn-id": "turn-completed",
        "last-assistant-message": (
            "The deployment preparation is complete for the selected target, and the "
            "configuration has been verified."
        ),
    })

    assert waiting is not None and completed is not None
    assert service.dispatch(waiting).status == "attempted"
    assert service.dispatch(completed).status == "attempted"

    assert len(desktop.items) == 2
    assert len(sounds.items) == 2
    assert len(bark.items) == 2
    entries = history.read()
    assert [entry["type"] for entry in entries] == [
        Category.INPUT_REQUIRED.value,
        Category.TASK_COMPLETED.value,
    ]
    assert {entry["title"] for entry in entries} == {
        "Codex Needs Attention · PourDeploy"
    }
    assert all(len(entry["message"]) <= 160 for entry in entries)
    assert all("deployment preparation is complete" not in entry["message"] for entry in entries)


@pytest.fixture
def appointment_pipeline(tmp_path):
    config = AppConfig(bark_enabled=True, bark_device_key="configured")
    for category in (Category.INPUT_REQUIRED, Category.TASK_COMPLETED):
        settings = config.categories[category.value]
        settings.enabled = settings.desktop = settings.sound = settings.bark = settings.history = True
    history = HistoryStore(tmp_path / "history.json")
    desktop, sounds = Recorder(), Recorder()
    bark = Recorder(BarkDeliveryResult(200, '{"code":200}'))
    service = NotificationDispatcher(config, history, desktop, sounds, bark)
    fixture = Path(__file__).parent / "fixtures/input_required_appointment.json"
    return SimpleNamespace(
        payload=json.loads(fixture.read_text(encoding="utf-8")),
        window=SimpleNamespace(dispatcher=service),
        history=history,
        channels=(desktop, sounds, bark),
        ledger=CodexLifecycleLedger(tmp_path / "ledger.sqlite3"),
        diagnostics=NotificationDiagnostics(tmp_path / "diagnostics.jsonl"),
    )


def dispatch_appointment(pipeline, source, *, payload=None, thread_source="user"):
    return dispatch_codex_payload(
        pipeline.window,
        json.dumps(pipeline.payload if payload is None else payload),
        pipeline.diagnostics,
        notify_source=source,
        lifecycle_ledger=pipeline.ledger,
        observer_version=OBSERVER_VERSION if source == "codex_local_fallback" else "",
        thread_source_resolver=lambda thread_id: thread_source,
    )


def appointment_diagnostics(pipeline):
    return [
        json.loads(line)
        for line in pipeline.diagnostics.path.read_text(encoding="utf-8").splitlines()
    ]


def test_chinese_create_thread_wait_dispatches_input_once(appointment_pipeline, tmp_path):
    from test_codex_observer import (
        FIXED_NOW,
        _codex_app_completed_turn,
        _session_meta,
        _write_records,
    )

    from pournotify.services.codex_observer import CodexRolloutObserver

    pipeline = appointment_pipeline
    prompt = (
        "PR6-CONTEXT-CASE2。请写一句可复制到日历的预约提醒。"
        "目前尚未提供预约日期和开始时间。不要自行猜测；"
        "请询问缺少的信息，然后停止等待。不要创建其他任务或子代理。"
    )
    response = "请提供预约日期和开始时间，我再帮你写一句可复制到日历的预约提醒。"
    observed = []

    def dispatch(candidate):
        observed.append(candidate)
        dispatch_appointment(pipeline, "codex_local_fallback", payload=candidate)

    sessions = tmp_path / "sessions"
    sessions.mkdir()
    observer = CodexRolloutObserver(sessions, dispatch, enabled=True, clock=lambda: FIXED_NOW)
    thread, turn = "thread-chinese-case", "turn-chinese-case"
    _write_records(
        sessions / "2026/08/30/rollout-chinese-case.jsonl",
        [_session_meta(thread, thread_source="agent_created_thread"),
         *_codex_app_completed_turn(thread, turn, prompt, response)],
    )
    observer.poll_once()
    assert len(observed) == 1
    assert not dispatch_appointment(pipeline, "ipc", payload=observed[0])
    assert [len(channel.items) for channel in pipeline.channels] == [1, 1, 1]
    assert [(row["type"], row["count"]) for row in pipeline.history.read()] == [
        ("input_required", 1)
    ]
    assert appointment_diagnostics(pipeline)[0]["classification_reason"] == (
        "blocked_until_user_action"
    )
    assert prompt not in pipeline.diagnostics.path.read_text(encoding="utf-8")
    assert response not in pipeline.history.path.read_text(encoding="utf-8")


@pytest.mark.parametrize("first_source", ["ipc", "codex_local_fallback"])
def test_blocking_appointment_question_delivers_once_across_both_paths(
    appointment_pipeline, first_source
):
    pipeline = appointment_pipeline
    second_source = "codex_local_fallback" if first_source == "ipc" else "ipc"

    assert dispatch_appointment(pipeline, first_source)
    assert not dispatch_appointment(pipeline, second_source)

    assert [len(channel.items) for channel in pipeline.channels] == [1, 1, 1]
    entries = pipeline.history.read()
    assert [(entry["type"], entry["count"]) for entry in entries] == [("input_required", 1)]
    assert entries[0]["title"].startswith("Codex Needs Attention · ")
    assert entries[0]["message"] == "Codex needs your input before it can continue."
    records = appointment_diagnostics(pipeline)
    assert records[0]["attention_reason"] == "input_required"
    assert records[0]["classification_reason"] == "blocking_required_question"
    assert records[1]["dispatch_status"] == "lifecycle_duplicate"
    assert records[1]["dedupe_result"] == "already_claimed"
    for channel in ("desktop", "sound", "bark", "history"):
        assert records[0][f"{channel}_attempted"] is True
        assert records[1][f"{channel}_attempted"] is False


def test_contextless_hook_does_not_claim_before_fallback_recovers_required_input(
    appointment_pipeline,
):
    pipeline = appointment_pipeline
    missing_context = {**pipeline.payload, "input-messages": []}
    assert not dispatch_appointment(pipeline, "ipc", payload=missing_context)
    assert dispatch_appointment(pipeline, "codex_local_fallback")
    assert not dispatch_appointment(pipeline, "ipc")

    assert [len(channel.items) for channel in pipeline.channels] == [1, 1, 1]
    assert [(entry["type"], entry["count"]) for entry in pipeline.history.read()] == [
        ("input_required", 1)
    ]
    records = appointment_diagnostics(pipeline)
    assert records[0]["classification_reason"] == "missing_user_context"
    assert records[1]["dedupe_result"] == "claimed"
    assert records[2]["dedupe_result"] == "already_claimed"
    for channel in ("desktop", "sound", "bark", "history"):
        assert records[0][f"{channel}_attempted"] is False


@pytest.mark.parametrize(
    ("thread_source", "reason"),
    [("subagent", "subagent_thread"), ("", "unverified_thread_source")],
)
def test_blocking_question_does_not_bypass_source_suppression(
    appointment_pipeline, thread_source, reason
):
    pipeline = appointment_pipeline
    assert not dispatch_appointment(pipeline, "ipc", thread_source=thread_source)
    assert all(not channel.items for channel in pipeline.channels)
    assert pipeline.history.read() == []
    record = appointment_diagnostics(pipeline)[0]
    assert record["classification_reason"] == reason
    for channel in ("desktop", "sound", "bark", "history"):
        assert record[f"{channel}_attempted"] is False


def test_blocking_question_respects_validation_controller_preclaim(appointment_pipeline):
    pipeline = appointment_pipeline
    assert pipeline.ledger.claim(
        pipeline.payload["thread-id"], pipeline.payload["turn-id"], "validation_controller"
    ).claimed
    assert not dispatch_appointment(pipeline, "ipc")
    assert not dispatch_appointment(pipeline, "codex_local_fallback")
    assert all(not channel.items for channel in pipeline.channels)
    assert pipeline.history.read() == []
    for record in appointment_diagnostics(pipeline):
        assert record["dedupe_result"] == "already_claimed"
        for channel in ("desktop", "sound", "bark", "history"):
            assert record[f"{channel}_attempted"] is False

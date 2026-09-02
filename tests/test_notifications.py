from datetime import UTC, datetime

from pournotify.config import AppConfig
from pournotify.models import Category, Notification, Priority
from pournotify.services.codex import parse_codex_event
from pournotify.services.delivery import BarkDeliveryResult
from pournotify.services.dispatcher import NotificationDispatcher
from pournotify.services.history import HistoryStore


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

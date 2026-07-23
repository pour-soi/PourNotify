import json

from pournotify.config import AppConfig, ConfigStore
from pournotify.models import Category
from pournotify.services.codex import parse_codex_event


def test_config_round_trip_and_unknown_keys(tmp_path):
    path = tmp_path / "config.json"
    store = ConfigStore(path)
    config = AppConfig()
    config.categories[Category.LOW_QUOTA.value].desktop = False
    store.save(config)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["future"] = True
    path.write_text(json.dumps(raw), encoding="utf-8")
    assert store.load().categories[Category.LOW_QUOTA.value].desktop is False


def test_codex_complete_parsing_and_truncation():
    notice = parse_codex_event({
        "type": "agent-turn-complete", "cwd": r"F:\work\PourCase",
        "last-assistant-message": "x" * 600, "turn-id": "turn-1",
    })
    assert notice.category == Category.TASK_COMPLETED
    assert notice.project == "PourCase"
    assert len(notice.message) == 600
    assert notice.system_generated is True
    assert notice.deduplication_id == "turn-1"


def test_unknown_codex_event_is_safe():
    assert parse_codex_event({"type": "future-event"}) is None

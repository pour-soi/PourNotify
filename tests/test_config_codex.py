import json

import pytest

from pournotify.config import AppConfig, ConfigStore
from pournotify.models import Category
from pournotify.services.codex import parse_codex_event


def completion_payload(**overrides):
    payload = {
        "type": "agent-turn-complete",
        "thread-id": "thread-sanitized",
        "turn-id": "turn-sanitized",
        "input-messages": ["Inspect the repository and report the relevant result."],
        "last-assistant-message": (
            "The repository inspection found the requested configuration in the shared "
            "service, with no unrelated files changed."
        ),
    }
    payload.update(overrides)
    return payload


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
    notice = parse_codex_event(completion_payload(**{
        "cwd": r"F:\work\PourCase",
        "last-assistant-message": "x" * 600,
        "turn-id": "turn-1",
    }))
    assert notice is not None
    assert notice.category == Category.TASK_COMPLETED
    assert notice.project == "PourCase"
    assert len(notice.message) == 600
    assert notice.system_generated is True
    assert notice.deduplication_id == "turn-1"


@pytest.mark.parametrize(
    ("workspace", "expected"),
    [
        (r"F:\work\PourCase", "PourCase"),
        ("/projects/PourNotify", "PourNotify"),
        (r"C:\work\Pour Case", "Pour Case"),
        ("/projects/通知 项目", "通知 项目"),
        ("C:/work/PourNotify/", "PourNotify"),
        (r"F:\work\PourCase\\", "PourCase"),
        ("/work/PourCase/", "PourCase"),
    ],
)
def test_codex_project_name_supports_foreign_path_styles(workspace, expected):
    notice = parse_codex_event(completion_payload(cwd=workspace))
    assert notice is not None
    assert notice.project == expected


@pytest.mark.parametrize("workspace", ["", "   ", None, 123, "\0invalid"])
def test_codex_project_name_safely_handles_invalid_input(workspace):
    notice = parse_codex_event(completion_payload(cwd=workspace))
    assert notice is not None
    assert notice.project == "Codex"


def test_unknown_codex_event_is_safe():
    assert parse_codex_event({"type": "future-event"}) is None

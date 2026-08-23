import json

import pytest

from pournotify.config import AppConfig, ConfigStore, default_categories
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


def test_new_input_required_category_is_added_to_existing_config(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"categories":{"task_completed":{"enabled":false}}}', encoding="utf-8")

    config = ConfigStore(path).load()

    assert Category.INPUT_REQUIRED.value in config.categories
    assert config.categories[Category.INPUT_REQUIRED.value].enabled is True
    assert config.categories[Category.INPUT_REQUIRED.value].priority.value == "critical"
    assert set(default_categories()) == {category.value for category in Category}


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


@pytest.mark.parametrize(
    ("message", "expected_category", "expected_title"),
    [
        (
            "I need your target environment before I can continue with the deployment.",
            Category.INPUT_REQUIRED,
            "Codex Needs Your Input",
        ),
        (
            "I need your approval before I can continue with the production operation.",
            Category.APPROVAL_REQUIRED,
            "Codex Approval Required",
        ),
    ],
)
def test_blocking_codex_turn_routes_to_owner_action_category(
    message, expected_category, expected_title
):
    notice = parse_codex_event(completion_payload(**{"last-assistant-message": message}))

    assert notice is not None
    assert notice.category == expected_category
    assert notice.title == expected_title
    assert notice.deduplication_id == "turn-sanitized"
    assert message not in notice.message


def test_waiting_then_completion_are_two_distinct_lifecycle_notifications():
    waiting = parse_codex_event(completion_payload(**{
        "turn-id": "turn-waiting",
        "last-assistant-message": (
            "I need your target environment before I can continue with the deployment."
        ),
    }))
    completed = parse_codex_event(completion_payload(**{"turn-id": "turn-completed"}))

    assert waiting is not None and completed is not None
    assert [waiting.category, completed.category] == [
        Category.INPUT_REQUIRED,
        Category.TASK_COMPLETED,
    ]
    assert waiting.deduplication_id != completed.deduplication_id


def test_internal_summary_after_lifecycle_notification_does_not_route():
    internal = completion_payload(**{
        "turn-id": "turn-internal",
        "input-messages": [
            (
                "You write the one-line activity update displayed beneath an existing Codex "
                "task title. Fill the structured summary field with one plain-text sentence."
            )
        ],
        "last-assistant-message": '{"summary":"Waiting for owner input."}',
    })

    assert parse_codex_event(internal) is None

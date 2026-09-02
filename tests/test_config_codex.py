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


def test_local_fallback_detection_is_opt_in_and_round_trips(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"theme":"dark"}', encoding="utf-8")
    store = ConfigStore(path)

    config = store.load()
    assert config.codex_local_fallback_enabled is False

    config.codex_local_fallback_enabled = True
    store.save(config)

    assert store.load().codex_local_fallback_enabled is True


@pytest.mark.parametrize("value", ["false", 1, [], {}])
def test_malformed_local_fallback_setting_fails_closed(value):
    config = AppConfig.from_dict({"codex_local_fallback_enabled": value})
    assert config.codex_local_fallback_enabled is False


def test_existing_v105_settings_load_unchanged_with_fallback_disabled(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "bark_enabled": True,
                "bark_device_key": "configured-but-not-logged",
                "quiet_hours_enabled": True,
                "quiet_start": "21:30",
                "quiet_end": "07:15",
                "start_with_windows": True,
                "custom_sounds": {"owner": "C:/Sounds/owner.wav"},
                "categories": {
                    "task_completed": {"enabled": True, "bark": True},
                    "input_required": {"enabled": True, "bark": True},
                    "task_failed": {"enabled": False},
                },
            }
        ),
        encoding="utf-8",
    )

    config = ConfigStore(path).load()

    assert config.codex_local_fallback_enabled is False
    assert config.bark_enabled is True
    assert config.bark_device_key == "configured-but-not-logged"
    assert (config.quiet_start, config.quiet_end) == ("21:30", "07:15")
    assert config.start_with_windows is True
    assert config.custom_sounds == {"owner": "C:/Sounds/owner.wav"}
    assert config.categories[Category.TASK_COMPLETED.value].bark is True
    assert config.categories[Category.TASK_FAILED.value].enabled is False


def test_finished_attention_notification_is_short_and_excludes_raw_result():
    private_result = "Commit abc123 at F:/private/project.\n```\nprivate command output\n```"
    notice = parse_codex_event(completion_payload(**{
        "cwd": r"F:\work\PourCase",
        "last-assistant-message": private_result,
        "turn-id": "turn-1",
    }))
    assert notice is not None
    assert notice.category == Category.TASK_COMPLETED
    assert notice.title == "Codex Needs Attention · PourCase"
    assert notice.message == "Task finished and is waiting for your next instruction."
    assert notice.project == "PourCase"
    assert len(notice.message) <= 160
    assert "abc123" not in notice.message
    assert "private" not in notice.message
    assert notice.system_generated is True
    assert notice.deduplication_id == "codex:thread-sanitized:turn-1"


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
    assert notice.title == f"Codex Needs Attention · {expected}"


@pytest.mark.parametrize("workspace", ["", "   ", None, 123, "\0invalid"])
def test_codex_project_name_safely_handles_invalid_input(workspace):
    notice = parse_codex_event(completion_payload(cwd=workspace))
    assert notice is not None
    assert notice.project == "Codex"
    assert notice.title == "Codex Needs Attention"


def test_unknown_codex_event_is_safe():
    assert parse_codex_event({"type": "future-event"}) is None


@pytest.mark.parametrize(
    ("message", "expected_category", "expected_body"),
    [
        (
            "I need your target environment before I can continue with the deployment.",
            Category.INPUT_REQUIRED,
            "Codex needs your input before it can continue.",
        ),
        (
            "I need your approval before I can continue with the production operation.",
            Category.APPROVAL_REQUIRED,
            "Codex needs your approval before it can continue.",
        ),
    ],
)
def test_blocking_codex_turn_routes_to_owner_action_category(
    message, expected_category, expected_body
):
    notice = parse_codex_event(completion_payload(**{"last-assistant-message": message}))

    assert notice is not None
    assert notice.category == expected_category
    assert notice.title == "Codex Needs Attention"
    assert notice.message == expected_body
    assert len(notice.message) <= 160
    assert notice.deduplication_id == "codex:thread-sanitized:turn-sanitized"
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
    assert waiting.title == completed.title == "Codex Needs Attention"
    assert waiting.message != completed.message


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

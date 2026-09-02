from pournotify.models import Category, Notification
from pournotify.services.content import (
    PREVIEW_LIMIT,
    copy_text,
    entry_priority,
    history_preview,
    normalize_system_title,
)
from pournotify.services.test_cases import LONG_TEST_MESSAGE, notification_test_cases


def test_preview_is_collapsed_without_changing_original():
    original = "Paragraph " * 100
    preview = history_preview(original)
    assert len(preview) <= PREVIEW_LIMIT
    assert preview.endswith("…")
    assert original == "Paragraph " * 100


def test_preview_cleans_markdown_table_and_code_fences():
    original = (
        "```\n| Test | Result | Evidence |\n|---|---|---|\n"
        "| Normal | Pass | Bark accepted |\n```"
    )
    preview = history_preview(original)
    assert "```" not in preview
    assert "---" not in preview
    assert "Test — Result — Evidence" in preview
    assert "Normal — Pass — Bark accepted" in preview


def test_preview_limits_repeated_characters():
    preview = history_preview("L" * 800)
    assert len(preview) < 30
    assert preview.endswith("…")


def test_system_title_normalization_and_custom_preservation():
    system = Notification(
        Category.TASK_COMPLETED, "Codex completed", "Body", system_generated=True
    )
    custom = Notification(Category.TASK_COMPLETED, "My Custom Title", "Body")
    needs_input = Notification(
        Category.INPUT_REQUIRED, "Input Required", "Body", system_generated=True
    )
    qualified = Notification(
        Category.TASK_COMPLETED,
        "Codex Needs Attention · PourInput",
        "Body",
        system_generated=True,
    )
    assert normalize_system_title(system).title == "Codex Needs Attention"
    assert normalize_system_title(custom).title == "My Custom Title"
    assert normalize_system_title(needs_input).title == "Codex Needs Attention"
    assert normalize_system_title(qualified).title == "Codex Needs Attention · PourInput"
    input_required = Notification(
        Category.SYSTEM_EVENTS, "Input Required", "Body", system_generated=True
    )
    unknown = Notification(
        Category.SYSTEM_EVENTS, "Unknown Event", "Body", system_generated=True
    )
    assert normalize_system_title(input_required).title == "Codex Needs Attention"
    assert normalize_system_title(unknown).title == "Unknown Codex Event"


def test_copy_uses_full_original_and_old_priority_defaults_normal():
    entry = {"title": "Title", "message": "M" * 500}
    assert copy_text(entry) == "Title\n\n" + "M" * 500
    assert entry_priority(entry) == "normal"


def test_predefined_tests_use_realistic_and_identifiable_content():
    cases = notification_test_cases()
    assert "repeated L" not in LONG_TEST_MESSAGE
    assert len(LONG_TEST_MESSAGE) > PREVIEW_LIMIT
    assert any(case.label == "Codex Needs Attention: Finished" for case in cases)
    assert any(case.label.startswith("Critical:") for case in cases)
    assert any(case.label.startswith("High:") for case in cases)
    assert any(case.duplicate and case.notification.title == "Duplicate Merge Test" for case in cases)
    assert any(case.label.startswith("Layout stress:") for case in cases)

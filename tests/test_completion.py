from __future__ import annotations

import pytest

from pournotify.services.completion import (
    CLASSIFIER_VERSION,
    CompletionClassification,
    classify_completion,
)


def payload(message: str, input_message: str = "Inspect the project and report the result."):
    return {
        "type": "agent-turn-complete",
        "thread-id": "thread-sanitized",
        "turn-id": "turn-sanitized",
        "cwd": r"F:\work\Example",
        "client": "Codex Desktop",
        "input-messages": [input_message],
        "last-assistant-message": message,
    }


@pytest.mark.parametrize(
    ("input_message", "message", "reason"),
    [
        (
            (
                "You write the one-line activity update displayed beneath an existing Codex "
                "task title. Fill the structured summary field with one plain-text sentence."
            ),
            '{"summary":"The requested work completed."}',
            "activity_summary_turn",
        ),
        (
            (
                "You are a helpful assistant. You will be presented with a user prompt, and "
                "your job is to provide a short title for a task that will be created from "
                "that prompt."
            ),
            '{"title":"Inspect project","description":"Review project behavior"}',
            "task_title_generation_turn",
        ),
        (
            (
                "Generate UI metadata for this task. Do not answer the request; only fill the "
                "summary field."
            ),
            '{"summary":"Generate an internal status update"}',
            "ui_metadata_turn",
        ),
        (
            "Update the task title from the latest request. Do not answer the user.",
            '{"title":"Updated task title"}',
            "task_title_update_turn",
        ),
        (
            "Summarize the conversation for internal continuity. Do not answer the request.",
            '{"summary":"Internal conversation summary"}',
            "conversation_summary_turn",
        ),
        (
            "Write the status update displayed in the task list. Do not answer the request.",
            '{"summary":"Internal status update"}',
            "internal_status_turn",
        ),
    ],
)
def test_known_internal_codex_turns_are_suppressed(input_message, message, reason):
    decision = classify_completion(payload(message, input_message))

    assert decision.classification == CompletionClassification.SUPPRESSED_INTERNAL
    assert decision.reason == reason
    assert decision.classifier_version == CLASSIFIER_VERSION
    assert decision.should_notify is False


@pytest.mark.parametrize(
    ("message", "classification", "reason"),
    [
        (
            (
                "I need you to provide the target environment before I can continue with the "
                "deployment investigation."
            ),
            CompletionClassification.SUPPRESSED_WAITING,
            "required_user_input",
        ),
        (
            (
                "Preflight checks passed. Please confirm: may I launch the isolated fixture "
                "and proceed with the UI-driven installation?"
            ),
            CompletionClassification.SUPPRESSED_WAITING,
            "approval_required",
        ),
        (
            (
                "I am still working through the verification matrix and will report the "
                "result after the remaining checks."
            ),
            CompletionClassification.SUPPRESSED_INTERMEDIATE,
            "work_still_in_progress",
        ),
        (
            (
                "Count: 6 Sum: 237 Mean: 39.5 Checkpoint: The analysis is still in "
                "progress. Remaining work: calculate the median, range, and values above "
                "the mean. Send CONTINUE to proceed."
            ),
            CompletionClassification.SUPPRESSED_INTERMEDIATE,
            "work_still_in_progress",
        ),
        (
            (
                "Stage 4 stopped at a mandatory condition and is not complete. No destructive "
                "cleanup was attempted."
            ),
            CompletionClassification.SUPPRESSED_INTERMEDIATE,
            "explicitly_incomplete",
        ),
    ],
)
def test_confident_non_final_states_are_suppressed(message, classification, reason):
    decision = classify_completion(payload(message))

    assert decision.classification == classification
    assert decision.reason == reason
    assert decision.should_notify is False


def test_real_style_chinese_required_questions_are_suppressed():
    decision = classify_completion(payload(
        "以下几点会实质影响设计，需要你确认。你可以逐项回答；收到确认后，我会先提交架构方案供你审批。"
    ))

    assert decision.classification == CompletionClassification.SUPPRESSED_WAITING
    assert decision.reason == "required_user_input"


@pytest.mark.parametrize(
    ("message", "reason"),
    [
        ("Noted.", "insufficient_substance"),
        ("Which environment should I inspect?", "question_only_response"),
        ("A substantive answer without any user context is intentionally questionable.",
         "missing_user_context"),
    ],
)
def test_ambiguous_turns_are_suppressed(message, reason):
    item = payload(message)
    if reason == "missing_user_context":
        item["input-messages"] = []

    decision = classify_completion(item)

    assert decision.classification == CompletionClassification.AMBIGUOUS
    assert decision.reason == reason
    assert decision.should_notify is False


@pytest.mark.parametrize(
    "message",
    [
        (
            "The repository uses the shared parser in services/codex.py, and the requested "
            "behavior is covered by focused regression tests."
        ),
        (
            "The parser now ignores the internal metadata payload while retaining the normal "
            "user-facing result. Would you like me to inspect another example?"
        ),
        (
            "代码路径位于统一的通知分类层，相关回归测试覆盖内部元数据、等待状态和正常用户结果。"
        ),
    ],
)
def test_substantive_user_facing_results_notify_without_magic_words(message):
    decision = classify_completion(payload(message))

    assert decision.classification == CompletionClassification.HIGH_CONFIDENCE_COMPLETION
    assert decision.reason == "substantive_user_facing_result"
    assert decision.should_notify is True


def test_metadata_output_with_completed_word_remains_suppressed_without_prompt_signature():
    decision = classify_completion(payload('{"summary":"Everything completed successfully."}'))

    assert decision.classification == CompletionClassification.AMBIGUOUS
    assert decision.reason == "structured_summary_output"


def test_description_only_metadata_output_is_suppressed():
    decision = classify_completion(payload(
        '{"description":"Concise internal description for the sanitized validation task."}'
    ))

    assert decision.classification == CompletionClassification.AMBIGUOUS
    assert decision.reason == "structured_description_output"
    assert decision.should_notify is False


@pytest.mark.parametrize(
    "message",
    [
        "The task failed before producing a usable result.",
        "Cancelled: the requested operation did not run.",
    ],
)
def test_explicit_leading_failure_or_cancellation_is_ambiguous(message):
    decision = classify_completion(payload(message))

    assert decision.classification == CompletionClassification.AMBIGUOUS
    assert decision.reason == "reported_non_completion"


def test_final_audit_can_report_out_of_scope_incomplete_work():
    decision = classify_completion(payload(
        "The requested audit identified the active configuration and preserved all files. "
        "Stage 4 was not resumed because it was outside this audit's authorized scope."
    ))

    assert decision.classification == CompletionClassification.HIGH_CONFIDENCE_COMPLETION


def test_substantive_result_with_required_trailing_choice_is_ambiguous():
    decision = classify_completion(payload(
        "The repository supports two valid deployment targets. Which target should I "
        "configure?"
    ))

    assert decision.classification == CompletionClassification.AMBIGUOUS
    assert decision.reason == "unrecognized_trailing_question"

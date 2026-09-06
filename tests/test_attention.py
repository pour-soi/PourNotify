from __future__ import annotations

import json
from pathlib import Path

import pytest

from pournotify.services.attention import (
    CLASSIFIER_VERSION,
    AttentionReason,
    AttentionState,
    classify_attention,
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
def test_known_internal_codex_turns_do_not_need_attention(
    input_message, message, reason
):
    decision = classify_attention(payload(message, input_message))

    assert decision.state == AttentionState.SUPPRESSED_INTERNAL
    assert decision.classification_reason == reason
    assert decision.attention_reason is None
    assert decision.classifier_version == CLASSIFIER_VERSION
    assert decision.needs_attention is False


@pytest.mark.parametrize(
    ("message", "state", "attention_reason", "classification_reason"),
    [
        (
            (
                "I need you to provide the target environment before I can continue with the "
                "deployment investigation."
            ),
            AttentionState.NEEDS_ATTENTION,
            AttentionReason.INPUT_REQUIRED,
            "required_user_input",
        ),
        (
            (
                "Preflight checks passed. Please confirm: may I launch the isolated fixture "
                "and proceed with the UI-driven installation?"
            ),
            AttentionState.NEEDS_ATTENTION,
            AttentionReason.APPROVAL_REQUIRED,
            "approval_required",
        ),
        (
            (
                "I am still working through the verification matrix and will report the "
                "result after the remaining checks."
            ),
            AttentionState.SUPPRESSED_INTERMEDIATE,
            None,
            "work_still_in_progress",
        ),
        (
            (
                "Checkpoint: the first phase is complete. I am continuing automatically "
                "with the remaining calculations now."
            ),
            AttentionState.SUPPRESSED_INTERMEDIATE,
            None,
            "work_still_in_progress",
        ),
        (
            (
                "Stage 4 stopped at a mandatory condition and is not complete. No destructive "
                "cleanup was attempted."
            ),
            AttentionState.SUPPRESSED_INTERMEDIATE,
            None,
            "explicitly_incomplete",
        ),
    ],
)
def test_attention_and_working_states_are_distinguished(
    message, state, attention_reason, classification_reason
):
    decision = classify_attention(payload(message))

    assert decision.state == state
    assert decision.attention_reason == attention_reason
    assert decision.classification_reason == classification_reason
    assert decision.needs_attention is (state == AttentionState.NEEDS_ATTENTION)


def test_real_style_chinese_required_input_needs_attention():
    decision = classify_attention(
        payload(
            "以下几点会实质影响设计，需要你确认。你可以逐项回答；收到确认后，我会先提交架构方案供你审批。"
        )
    )

    assert decision.state == AttentionState.NEEDS_ATTENTION
    assert decision.attention_reason == AttentionReason.INPUT_REQUIRED
    assert decision.classification_reason == "required_user_input"


@pytest.mark.parametrize(
    ("message", "attention_reason", "classification_reason"),
    [
        (
            "I need your target environment before I can continue with the deployment.",
            AttentionReason.INPUT_REQUIRED,
            "required_user_input",
        ),
        (
            "Please confirm the destination before I can continue with the migration.",
            AttentionReason.INPUT_REQUIRED,
            "required_confirmation",
        ),
        (
            "I need your approval before I can continue with the production operation.",
            AttentionReason.APPROVAL_REQUIRED,
            "approval_required",
        ),
        (
            "Which environment should I inspect?",
            AttentionReason.INPUT_REQUIRED,
            "direct_owner_question",
        ),
        (
            "The repository supports two valid targets. Which target should I configure?",
            AttentionReason.INPUT_REQUIRED,
            "direct_owner_question",
        ),
        (
            "Preflight checks passed. Do you approve proceeding with the simulated cutover?",
            AttentionReason.APPROVAL_REQUIRED,
            "direct_owner_question",
        ),
        (
            (
                "Checkpoint: the analysis is still in progress. Remaining work is ready. "
                "Send CONTINUE to proceed."
            ),
            AttentionReason.INPUT_REQUIRED,
            "explicit_continue_gate",
        ),
        (
            "Please upload the required fixture file.",
            AttentionReason.INPUT_REQUIRED,
            "direct_owner_request",
        ),
        (
            "I need the target environment.",
            AttentionReason.INPUT_REQUIRED,
            "direct_owner_request",
        ),
        (
            "Please approve the proposed permission change.",
            AttentionReason.APPROVAL_REQUIRED,
            "direct_owner_request",
        ),
        (
            (
                "I am still working through the setup. "
                "Please upload the required fixture file."
            ),
            AttentionReason.INPUT_REQUIRED,
            "direct_owner_request",
        ),
    ],
)
def test_stopped_turns_with_required_owner_action_need_attention(
    message, attention_reason, classification_reason
):
    decision = classify_attention(payload(message))

    assert decision.state == AttentionState.NEEDS_ATTENTION
    assert decision.attention_reason == attention_reason
    assert decision.classification_reason == classification_reason
    assert decision.needs_attention is True


def test_finished_result_with_optional_question_needs_attention_as_finished():
    decision = classify_attention(
        payload(
            "The requested configuration review is complete and all relevant settings are "
            "consistent. Would you like me to also prepare a release note?"
        )
    )

    assert decision.state == AttentionState.NEEDS_ATTENTION
    assert decision.attention_reason == AttentionReason.FINISHED
    assert decision.classification_reason == "substantive_user_facing_stop"


@pytest.mark.parametrize(
    ("message", "reason"),
    [
        ("Noted.", "insufficient_substance"),
        ("Is that surprising?", "question_only_response"),
        (
            "A substantive answer without any user context is intentionally questionable.",
            "missing_user_context",
        ),
        (
            "The review found two patterns. Is that surprising?",
            "unrecognized_trailing_question",
        ),
    ],
)
def test_ambiguous_turns_are_suppressed(message, reason):
    item = payload(message)
    if reason == "missing_user_context":
        item["input-messages"] = []

    decision = classify_attention(item)

    assert decision.state == AttentionState.AMBIGUOUS
    assert decision.classification_reason == reason
    assert decision.attention_reason is None
    assert decision.needs_attention is False


def test_short_result_with_validated_local_task_stop_needs_attention():
    decision = classify_attention(
        payload("37 + 28 + 15 = 80 (37 + 28 = 65; 65 + 15 = 80)."),
        local_terminal_evidence=True,
    )

    assert decision.state == AttentionState.NEEDS_ATTENTION
    assert decision.attention_reason == AttentionReason.FINISHED
    assert decision.classification_reason == "validated_local_task_stop"


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
def test_substantive_user_facing_stops_need_attention_without_magic_words(message):
    decision = classify_attention(payload(message))

    assert decision.state == AttentionState.NEEDS_ATTENTION
    assert decision.attention_reason == AttentionReason.FINISHED
    assert decision.classification_reason == "substantive_user_facing_stop"


@pytest.mark.parametrize(
    ("message", "reason"),
    [
        ('{"summary":"Everything completed successfully."}', "structured_summary_output"),
        (
            '{"description":"Concise internal description for the sanitized validation task."}',
            "structured_description_output",
        ),
    ],
)
def test_metadata_output_remains_suppressed(message, reason):
    decision = classify_attention(payload(message))

    assert decision.state == AttentionState.SUPPRESSED_INTERNAL
    assert decision.classification_reason == reason
    assert decision.needs_attention is False


@pytest.mark.parametrize(
    "message",
    [
        "The requested work is complete. Would you like anything else?",
        "The requested work is complete. Anything else?",
        "The requested work is complete. Is there anything else I can help with?",
        "The requested work is complete. Please provide feedback if you'd like.",
    ],
)
def test_completed_result_with_optional_owner_prompt_is_finished(message):
    decision = classify_attention(payload(message))

    assert decision.state == AttentionState.NEEDS_ATTENTION
    assert decision.attention_reason == AttentionReason.FINISHED


@pytest.mark.parametrize(
    "message",
    [
        "No approval is required before I can continue.",
        "I don't need your approval before I can proceed.",
    ],
)
def test_negated_approval_language_does_not_request_approval(message):
    decision = classify_attention(payload(message))

    assert decision.state == AttentionState.SUPPRESSED_INTERMEDIATE
    assert decision.classification_reason == "explicitly_not_waiting_for_owner"
    assert decision.needs_attention is False


@pytest.mark.parametrize(
    "message",
    [
        "The task failed before producing a usable result.",
        "Cancelled: the requested operation did not run.",
    ],
)
def test_unmodeled_failure_or_cancellation_remains_ambiguous(message):
    decision = classify_attention(payload(message))

    assert decision.state == AttentionState.AMBIGUOUS
    assert decision.classification_reason == "reported_non_completion"


def test_final_audit_can_report_out_of_scope_incomplete_work_as_finished():
    decision = classify_attention(
        payload(
            "The requested audit identified the active configuration and preserved all files. "
            "Stage 4 was not resumed because it was outside this audit's authorized scope."
        )
    )

    assert decision.state == AttentionState.NEEDS_ATTENTION
    assert decision.attention_reason == AttentionReason.FINISHED


def appointment_fixture():
    return json.loads(
        (Path(__file__).parent / "fixtures/input_required_appointment.json").read_text(
            encoding="utf-8"
        )
    )


@pytest.mark.parametrize("ending", ["？", "。", "?", ".", "！", "!", ""])
@pytest.mark.parametrize("wording", [
    "请提供预约日期和开始时间", "请告诉我预约日期和开始时间",
    "我需要预约日期和开始时间才能继续", "还需要你提供预约日期和开始时间",
    "请补充缺少的日期和时间", "需要确认具体日期和开始时间",
    "预约日期和开始时间是什么", "请上传需要处理的文件",
    "请提供缺少的信息后我再继续",
    "请提供预约日期和开始时间，我再帮你写一句可复制到日历的预约提醒",
])
def test_chinese_blocking_input_is_independent_of_punctuation(wording, ending):
    item = payload(wording + ending, "预约日期和开始时间尚未提供。需要处理的文件未上传。")
    decision = classify_attention(item, local_terminal_evidence=True)
    assert decision.attention_reason == AttentionReason.INPUT_REQUIRED
    assert decision.classification_reason == "blocked_until_user_action"


@pytest.mark.parametrize("offer", [
    "需要我继续帮你处理吗？", "要不要我再给你一个版本？",
    "如果你愿意，我可以继续优化。", "需要我解释一下吗？",
    "你还需要我做其他事情吗？",
])
def test_chinese_optional_offer_after_completion_remains_finished(offer):
    item = payload("任务已经完成。" + offer, "预约日期和开始时间尚未提供。")
    decision = classify_attention(item, local_terminal_evidence=True)
    assert decision.attention_reason == AttentionReason.FINISHED


@pytest.mark.parametrize("context", [
    "解释预约日期和开始时间的含义。", "预约日期和开始时间已提供。",
    "缺少文件，请解释日期术语。",
])
def test_chinese_imperative_without_required_context_does_not_request_input(context):
    decision = classify_attention(payload("请提供预约日期和开始时间。", context),
                                  local_terminal_evidence=True)
    assert decision.attention_reason != AttentionReason.INPUT_REQUIRED


def test_missing_appointment_question_is_blocking_required_question():
    decision = classify_attention(appointment_fixture(), local_terminal_evidence=True)
    assert decision.state is AttentionState.NEEDS_ATTENTION
    assert decision.attention_reason is AttentionReason.INPUT_REQUIRED
    assert decision.classification_reason == "blocking_required_question"


@pytest.mark.parametrize("message", [
    "I need the tests to finish before I can proceed. I am still running them.",
    ("I need the file to finish downloading before I can proceed. "
     "I am still running the download."),
])
def test_waiting_for_running_work_is_not_waiting_for_owner(message):
    decision = classify_attention(payload(message), local_terminal_evidence=True)
    assert not decision.needs_attention
    assert decision.classification_reason == "work_still_in_progress"


@pytest.mark.parametrize("message", [
    "Which file should I use?",
    "What email address should I send this to?",
    "What value should I enter here?",
    "Which option do you want me to choose?",
    "Please provide the missing API endpoint before I continue.",
    "I need the exact date before I can proceed.",
])
def test_explicit_required_input_examples(message):
    decision = classify_attention(payload(message))
    assert decision.attention_reason is AttentionReason.INPUT_REQUIRED


@pytest.mark.parametrize("context", [
    "Write an appointment reminder.",
    "The appointment date and start time are September 5 at 10 AM.",
    "The file is missing; explain appointment date and start time terminology.",
    "Explain the meaning of appointment date and start time.",
])
def test_same_question_without_matching_missing_information_stays_ambiguous(context):
    item = appointment_fixture()
    item["input-messages"] = [context]
    decision = classify_attention(item, local_terminal_evidence=True)
    assert decision.state is AttentionState.AMBIGUOUS


def test_missing_parameter_question_requires_verified_stop_and_current_context():
    item = appointment_fixture()
    assert not classify_attention(item).needs_attention
    item["input-messages"].append("Both values are now supplied. Explain the format.")
    assert not classify_attention(item, local_terminal_evidence=True).needs_attention


@pytest.mark.parametrize("question", [
    "Would you like me to also update the README?",
    "Do you want me to explain this further?",
    "Should I give you another example?",
    "What is the meaning of time?",
    "Is that surprising?",
])
@pytest.mark.parametrize("completed", [False, True])
def test_optional_or_ambiguous_questions_never_become_required_input(question, completed):
    item = appointment_fixture()
    item["last-assistant-message"] = (
        "The requested work is complete. " if completed else ""
    ) + question
    decision = classify_attention(item, local_terminal_evidence=True)
    assert decision.attention_reason is not AttentionReason.INPUT_REQUIRED


def test_missing_parameter_question_cannot_override_internal_signature():
    item = appointment_fixture()
    item["input-messages"].insert(0,
        "Generate UI metadata. Do not answer the request; only fill the summary field."
    )
    decision = classify_attention(item, local_terminal_evidence=True)
    assert decision.state is AttentionState.SUPPRESSED_INTERNAL

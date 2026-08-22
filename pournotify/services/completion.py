from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

CLASSIFIER_VERSION = "1"


class CompletionClassification(StrEnum):
    HIGH_CONFIDENCE_COMPLETION = "high_confidence_completion"
    SUPPRESSED_INTERNAL = "suppressed_internal"
    SUPPRESSED_WAITING = "suppressed_waiting"
    SUPPRESSED_INTERMEDIATE = "suppressed_intermediate"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class CompletionDecision:
    classification: CompletionClassification
    reason: str
    classifier_version: str = CLASSIFIER_VERSION

    @property
    def should_notify(self) -> bool:
        return self.classification == CompletionClassification.HIGH_CONFIDENCE_COMPLETION


@dataclass(frozen=True, slots=True)
class InternalTurnSignature:
    reason: str
    required_fragments: tuple[str, ...]
    any_fragments: tuple[str, ...] = ()


# These signatures are anchored in Codex Desktop housekeeping instructions seen in real
# notify payloads. Keep them centralized and specific so ordinary user requests are not
# suppressed merely because they discuss titles, summaries, metadata, or status updates.
INTERNAL_TURN_SIGNATURES = (
    InternalTurnSignature(
        "activity_summary_turn",
        (
            (
                "you write the one-line activity update displayed beneath an existing codex "
                "task title."
            ),
            "fill the structured summary field",
        ),
    ),
    InternalTurnSignature(
        "task_title_generation_turn",
        (
            "you are a helpful assistant. you will be presented with a user prompt",
            "provide a short title for a task",
        ),
    ),
    InternalTurnSignature(
        "task_title_update_turn",
        ("update the task title",),
        ("do not answer the user", "do not answer the request"),
    ),
    InternalTurnSignature(
        "ui_metadata_turn",
        ("do not answer the request",),
        ("only fill the summary field", "only fill the title field", "generate ui metadata"),
    ),
    InternalTurnSignature(
        "conversation_summary_turn",
        ("summarize the conversation",),
        ("do not answer the user", "do not answer the request"),
    ),
    InternalTurnSignature(
        "internal_status_turn",
        ("status update displayed", "do not answer the request"),
    ),
)


WAITING_RULES = (
    (
        "required_user_input",
        re.compile(
            r"\b(?:i|we) (?:still )?(?:need|require) "
            r"(?:you to|your|the following).{0,160}\b(?:before|so that) "
            r"(?:i|we) can (?:continue|proceed|finish)",
        ),
    ),
    (
        "blocked_until_user_action",
        re.compile(
            r"\b(?:i|we) (?:cannot|can't|am unable to|are unable to) "
            r"(?:continue|proceed|finish).{0,160}\b(?:until|without)\b",
        ),
    ),
    (
        "request_missing_material",
        re.compile(
            r"\bplease (?:provide|attach|upload|send|choose|select|answer).{0,160}"
            r"\b(?:before|so) (?:i|we) can (?:continue|proceed|finish)",
        ),
    ),
    (
        "approval_required",
        re.compile(
            r"\b(?:need|require|awaiting|waiting for) (?:your )?"
            r"(?:approval|confirmation|authorization|permission)\b",
        ),
    ),
    (
        "approval_required",
        re.compile(
            r"\bplease (?:approve|confirm|authorize).{0,120}"
            r"\b(?:before|so) (?:i|we) (?:continue|proceed|can continue|can proceed)",
        ),
    ),
    (
        "approval_required",
        re.compile(r"\bplease confirm\s*:\s*(?:may|can|should) i\b"),
    ),
    (
        "waiting_for_user_action",
        re.compile(
            r"\b(?:waiting|blocked) (?:for|on) (?:your|the) "
            r"(?:input|answer|response|decision|choice|credentials|access)\b",
        ),
    ),
    (
        "required_user_input",
        re.compile(r"需要你(?:确认|提供|选择|回答)|收到(?:你的)?确认后.{0,80}(?:我|我们)会"),
    ),
    (
        "approval_required",
        re.compile(r"请确认\s*[:：]?\s*(?:是否|我可以|可否)|等待你的(?:批准|确认|授权)"),
    ),
)


INTERMEDIATE_RULES = (
    (
        "work_still_in_progress",
        re.compile(
            r"\b(?:i am|i'm|we are|we're) (?:still |currently )?"
            r"(?:working|continuing|investigating|checking|running|monitoring)\b",
        ),
    ),
    (
        "work_still_in_progress",
        re.compile(
            r"\b(?:work|analysis|investigation|validation|implementation) is (?:still )?"
            r"(?:in progress|underway|continuing)\b",
        ),
    ),
    (
        "continuation_announced",
        re.compile(
            r"\b(?:next|now) (?:i|we) (?:will|'ll) "
            r"(?:continue|investigate|implement|run|check|test)\b",
        ),
    ),
    (
        "continuation_announced",
        re.compile(r"\bi(?:'ll| will) continue (?:working|with|once|after)\b"),
    ),
    (
        "explicitly_incomplete",
        re.compile(
            r"\b(?:task|work|stage|validation|implementation).{0,120}"
            r"\b(?:is|remains) not (?:complete|finished)\b",
        ),
    ),
    (
        "work_still_in_progress",
        re.compile(r"(?:我|我们)(?:还在|仍在|正在)(?:继续|处理|检查|验证|调查|运行)"),
    ),
    (
        "continuation_announced",
        re.compile(r"下一步(?:我|我们)会继续|(?:任务|工作|验证)(?:仍在进行|尚未完成)"),
    ),
)


REPORTED_NON_COMPLETION_RULES = (
    re.compile(r"^(?:the )?(?:task|run|operation) (?:failed|was cancelled|was canceled)\b"),
    re.compile(r"^(?:cancelled|canceled)(?:[.: -]|$)"),
)


def _normalized(value: str) -> str:
    return " ".join(value.casefold().replace("’", "'").split())


def _first_input_message(payload: dict[str, Any]) -> str:
    messages = payload.get("input-messages")
    if not isinstance(messages, list) or not messages or not isinstance(messages[0], str):
        return ""
    return _normalized(messages[0])


def _internal_reason(payload: dict[str, Any]) -> str | None:
    first_message = _first_input_message(payload)
    for signature in INTERNAL_TURN_SIGNATURES:
        if not all(fragment in first_message for fragment in signature.required_fragments):
            continue
        if signature.any_fragments and not any(
            fragment in first_message for fragment in signature.any_fragments
        ):
            continue
        return signature.reason

    return None


def _metadata_shape(assistant_message: str) -> str | None:
    try:
        structured = json.loads(assistant_message)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(structured, dict) or not structured:
        return None
    keys = set(structured)
    if keys == {"summary"} and isinstance(structured["summary"], str):
        return "structured_summary_output"
    if keys == {"description"} and isinstance(structured["description"], str):
        return "structured_description_output"
    if "title" in keys and keys <= {"title", "description"} and all(
        isinstance(value, str) for value in structured.values()
    ):
        return "structured_title_output"
    return None


def _question_only(message: str) -> bool:
    stripped = message.rstrip()
    if not stripped.endswith(("?", "？")):
        return False
    before_question = stripped[:-1]
    return not re.search(r"[.!。！](?:\s|$)|\n", before_question)


def _has_unrecognized_trailing_question(message: str) -> bool:
    stripped = message.rstrip()
    if not stripped.endswith(("?", "？")):
        return False
    final_question = re.split(r"[.!。！\n]", stripped)[-1].strip().casefold()
    optional_starts = (
        "would you like me to ",
        "do you want me to ",
        "want me to ",
        "需要我",
    )
    return not final_question.startswith(optional_starts)


def classify_completion(payload: dict[str, Any]) -> CompletionDecision:
    if payload.get("type") != "agent-turn-complete":
        return CompletionDecision(CompletionClassification.AMBIGUOUS, "unsupported_event")

    assistant_value = payload.get("last-assistant-message")
    if not isinstance(assistant_value, str) or not assistant_value.strip():
        return CompletionDecision(CompletionClassification.AMBIGUOUS, "missing_assistant_result")
    assistant_message = assistant_value.strip()

    internal_reason = _internal_reason(payload)
    if internal_reason:
        return CompletionDecision(
            CompletionClassification.SUPPRESSED_INTERNAL,
            internal_reason,
        )

    metadata_shape = _metadata_shape(assistant_message)
    if metadata_shape:
        return CompletionDecision(CompletionClassification.AMBIGUOUS, metadata_shape)

    normalized_message = _normalized(assistant_message)
    if any(pattern.search(normalized_message) for pattern in REPORTED_NON_COMPLETION_RULES):
        return CompletionDecision(CompletionClassification.AMBIGUOUS, "reported_non_completion")
    for reason, pattern in WAITING_RULES:
        if pattern.search(normalized_message):
            return CompletionDecision(CompletionClassification.SUPPRESSED_WAITING, reason)

    for reason, pattern in INTERMEDIATE_RULES:
        if pattern.search(normalized_message):
            return CompletionDecision(CompletionClassification.SUPPRESSED_INTERMEDIATE, reason)
    if normalized_message.startswith("checkpoint") and "remaining" in normalized_message:
        return CompletionDecision(
            CompletionClassification.SUPPRESSED_INTERMEDIATE,
            "checkpoint_with_remaining_work",
        )

    messages = payload.get("input-messages")
    protocol_ids = (payload.get("thread-id"), payload.get("turn-id"))
    if not all(isinstance(value, str) and value.strip() for value in protocol_ids):
        return CompletionDecision(
            CompletionClassification.AMBIGUOUS,
            "malformed_or_incomplete_payload",
        )
    if (
        not isinstance(messages, list)
        or not messages
        or not all(isinstance(message, str) and message.strip() for message in messages)
    ):
        return CompletionDecision(CompletionClassification.AMBIGUOUS, "missing_user_context")
    if _question_only(assistant_message):
        return CompletionDecision(CompletionClassification.AMBIGUOUS, "question_only_response")
    if _has_unrecognized_trailing_question(assistant_message):
        return CompletionDecision(
            CompletionClassification.AMBIGUOUS,
            "unrecognized_trailing_question",
        )

    significant_characters = sum(character.isalnum() for character in assistant_message)
    if significant_characters < 24:
        return CompletionDecision(CompletionClassification.AMBIGUOUS, "insufficient_substance")

    return CompletionDecision(
        CompletionClassification.HIGH_CONFIDENCE_COMPLETION,
        "substantive_user_facing_result",
    )

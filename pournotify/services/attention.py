from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

CLASSIFIER_VERSION = "6"


class AttentionState(StrEnum):
    NEEDS_ATTENTION = "needs_attention"
    SUPPRESSED_INTERNAL = "suppressed_internal"
    SUPPRESSED_INTERMEDIATE = "suppressed_intermediate"
    AMBIGUOUS = "ambiguous"


class AttentionReason(StrEnum):
    FINISHED = "finished"
    INPUT_REQUIRED = "input_required"
    APPROVAL_REQUIRED = "approval_required"


@dataclass(frozen=True, slots=True)
class AttentionDecision:
    state: AttentionState
    classification_reason: str
    attention_reason: AttentionReason | None = None
    classifier_version: str = CLASSIFIER_VERSION

    @property
    def needs_attention(self) -> bool:
        return self.state == AttentionState.NEEDS_ATTENTION


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
        "approval_required",
        re.compile(
            r"\b(?:formal )?(?:owner )?approval is required before "
            r"(?:i|we) can (?:continue|proceed)\b",
        ),
    ),
    (
        "approval_required",
        re.compile(
            r"\b(?:need|require|awaiting|waiting for) (?:your )?"
            r"(?:approval|authorization|permission)\b",
        ),
    ),
    (
        "required_user_input",
        re.compile(
            r"\b(?:i|we) (?:still )?(?:need|require) "
            r"(?:you to|your|the following).{0,160}\b(?:before|so that) "
            r"(?:i|we) can (?:continue|proceed|finish)",
        ),
    ),
    (
        "required_user_input",
        re.compile(
            r"\b(?:i|we) (?:need|require) the (?:exact )?"
            r"(?:date|time|file|value|parameter|email address|api endpoint|"
            r"credential|option|material) before (?:i|we) can (?:continue|proceed)\b",
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
            r"\bplease (?:approve|authorize).{0,120}"
            r"\b(?:before|so) (?:i|we) (?:continue|proceed|can continue|can proceed)",
        ),
    ),
    (
        "approval_required",
        re.compile(r"\bplease confirm\s*:\s*(?:may|can|should) i\b"),
    ),
    (
        "required_confirmation",
        re.compile(
            r"\b(?:need|require|awaiting|waiting for) (?:your )?confirmation\b|"
            r"\bplease confirm.{0,120}\b(?:before|so) (?:i|we) "
            r"(?:continue|proceed|can continue|can proceed)",
        ),
    ),
    (
        "waiting_for_user_action",
        re.compile(
            r"\b(?:waiting|blocked) (?:for|on) (?:your|the) "
            r"(?:input|answer|response|decision|choice|credentials|access)\b",
        ),
    ),
    (
        "explicit_continue_gate",
        re.compile(
            r"\b(?:send|reply with|type) [a-z0-9_-]{1,40} to "
            r"(?:continue|proceed)\b",
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


WAITING_ATTENTION_REASONS = {
    "approval_required": AttentionReason.APPROVAL_REQUIRED,
    "required_user_input": AttentionReason.INPUT_REQUIRED,
    "required_confirmation": AttentionReason.INPUT_REQUIRED,
    "blocked_until_user_action": AttentionReason.INPUT_REQUIRED,
    "request_missing_material": AttentionReason.INPUT_REQUIRED,
    "waiting_for_user_action": AttentionReason.INPUT_REQUIRED,
    "explicit_continue_gate": AttentionReason.INPUT_REQUIRED,
}


DIRECT_APPROVAL_QUESTION = re.compile(
    r"^(?:do you approve|may i proceed|can i proceed|should i proceed|"
    r"请(?:批准|确认|授权)|我可以继续吗)\b"
)


DIRECT_INPUT_QUESTION = re.compile(
    r"^(?:(?:which|what|where|when|who)\b.{0,160}\b(?:should|would|do|can)\b|"
    r"(?:can|could|would) you (?:provide|choose|select|clarify|attach|upload|send)\b|"
    r"(?:please )?(?:provide|choose|select|attach|upload|send)\b|"
    r"(?:请)?(?:提供|选择|上传|附上|告诉我|说明))"
)


DIRECT_APPROVAL_STATEMENT = re.compile(
    r"^(?:please )?(?:approve|authorize)\b.{0,160}[.!]?$"
)


DIRECT_INPUT_STATEMENT = re.compile(
    r"^(?:(?:please )?(?:provide|choose|select|attach|upload|send|enter|clarify)\b|"
    r"(?:i|we) (?:still )?(?:need|require) (?:your |the )?"
    r"(?:input|answer|response|decision|choice|credentials|access|api key|password|"
    r"target environment|destination|file|material|value)\b).{0,160}[.!]?$"
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


NEGATED_OWNER_ACTION_RULES = (
    re.compile(
        r"\bno (?:owner )?(?:approval|authorization|permission|input|confirmation) "
        r"is required\b"
    ),
    re.compile(
        r"\b(?:i|we) (?:do not|don't) need (?:your )?"
        r"(?:approval|authorization|permission|input|confirmation)\b"
    ),
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


def _final_question(message: str) -> str:
    stripped = message.rstrip()
    if not stripped.endswith(("?", "？")):
        return ""
    return re.split(r"[.!。！\n]", stripped)[-1].strip().casefold().rstrip("?？").strip()


def _final_statement(message: str) -> str:
    statements = [
        statement.strip()
        for statement in re.split(r"[.!?。！？\n]", message)
        if statement.strip()
    ]
    return statements[-1] if statements else ""


def _is_optional_follow_up(question: str) -> bool:
    optional_starts = (
        "would you like me to ",
        "would you like anything else",
        "do you want me to ",
        "is there anything else",
        "anything else",
        "want me to ",
        "需要我",
    )
    return question.startswith(optional_starts)


def _required_question_reason(message: str) -> AttentionReason | None:
    question = _final_question(message)
    if not question or _is_optional_follow_up(question):
        return None
    if DIRECT_APPROVAL_QUESTION.search(question):
        return AttentionReason.APPROVAL_REQUIRED
    if DIRECT_INPUT_QUESTION.search(question):
        return AttentionReason.INPUT_REQUIRED
    return None


def _direct_request_reason(message: str) -> AttentionReason | None:
    normalized = _normalized(_final_statement(message))
    if " if you'd like" in normalized or " if you would like" in normalized:
        return None
    if DIRECT_APPROVAL_STATEMENT.fullmatch(normalized):
        return AttentionReason.APPROVAL_REQUIRED
    if DIRECT_INPUT_STATEMENT.fullmatch(normalized):
        return AttentionReason.INPUT_REQUIRED
    return None


def _blocking_parameter_question(message: str, current_input: str) -> bool:
    # A stopped question is not enough: the same requested parameter must be
    # explicitly missing in this turn's input, not just mentioned elsewhere.
    question = re.fullmatch(
        r"what (?:is|are) (?:the|your) ([a-z][a-z -]{0,100})",
        _final_question(message),
    )
    if question is None:
        return False
    parameter = question[1]
    if not re.search(
        r"\b(?:date|time|file|value|parameter|email address|api endpoint|"
        r"credentials?|option|material)$", parameter
    ):
        return False
    parameter = re.escape(parameter)
    return re.search(
        rf"\b{parameter}\s+(?:(?:is|are|was|were|has|have)\s+)?(?:still\s+)?"
        r"(?:missing|not (?:yet )?(?:been )?(?:provided|supplied|specified|given))\b|"
        rf"\bmissing (?:the )?{parameter}\b",
        _normalized(current_input),
    ) is not None


def classify_attention(
    payload: dict[str, Any], *, local_terminal_evidence: bool = False
) -> AttentionDecision:
    if payload.get("type") != "agent-turn-complete":
        return AttentionDecision(AttentionState.AMBIGUOUS, "unsupported_event")

    assistant_value = payload.get("last-assistant-message")
    if not isinstance(assistant_value, str) or not assistant_value.strip():
        return AttentionDecision(AttentionState.AMBIGUOUS, "missing_assistant_result")
    assistant_message = assistant_value.strip()

    internal_reason = _internal_reason(payload)
    if internal_reason:
        return AttentionDecision(
            AttentionState.SUPPRESSED_INTERNAL,
            internal_reason,
        )

    metadata_shape = _metadata_shape(assistant_message)
    if metadata_shape:
        return AttentionDecision(AttentionState.SUPPRESSED_INTERNAL, metadata_shape)

    normalized_message = _normalized(assistant_message)
    if any(pattern.search(normalized_message) for pattern in REPORTED_NON_COMPLETION_RULES):
        return AttentionDecision(AttentionState.AMBIGUOUS, "reported_non_completion")
    if any(pattern.search(normalized_message) for pattern in NEGATED_OWNER_ACTION_RULES):
        return AttentionDecision(
            AttentionState.SUPPRESSED_INTERMEDIATE,
            "explicitly_not_waiting_for_owner",
        )
    for reason, pattern in WAITING_RULES:
        if pattern.search(normalized_message):
            return AttentionDecision(
                AttentionState.NEEDS_ATTENTION,
                reason,
                WAITING_ATTENTION_REASONS[reason],
            )

    direct_request = _direct_request_reason(assistant_message)
    if direct_request is not None:
        return AttentionDecision(
            AttentionState.NEEDS_ATTENTION,
            "direct_owner_request",
            direct_request,
        )
    required_question = _required_question_reason(assistant_message)
    if required_question is not None:
        return AttentionDecision(
            AttentionState.NEEDS_ATTENTION,
            "direct_owner_question",
            required_question,
        )

    for reason, pattern in INTERMEDIATE_RULES:
        if pattern.search(normalized_message):
            return AttentionDecision(AttentionState.SUPPRESSED_INTERMEDIATE, reason)
    if normalized_message.startswith("checkpoint") and "remaining" in normalized_message:
        return AttentionDecision(
            AttentionState.SUPPRESSED_INTERMEDIATE,
            "checkpoint_with_remaining_work",
        )

    messages = payload.get("input-messages")
    protocol_ids = (payload.get("thread-id"), payload.get("turn-id"))
    if not all(isinstance(value, str) and value.strip() for value in protocol_ids):
        return AttentionDecision(
            AttentionState.AMBIGUOUS,
            "malformed_or_incomplete_payload",
        )
    if (
        not isinstance(messages, list)
        or not messages
        or not all(isinstance(message, str) and message.strip() for message in messages)
    ):
        return AttentionDecision(AttentionState.AMBIGUOUS, "missing_user_context")

    if _question_only(assistant_message):
        if local_terminal_evidence and _blocking_parameter_question(
            assistant_message, messages[-1]
        ):
            return AttentionDecision(
                AttentionState.NEEDS_ATTENTION,
                "blocking_required_question",
                AttentionReason.INPUT_REQUIRED,
            )
        return AttentionDecision(AttentionState.AMBIGUOUS, "question_only_response")
    final_question = _final_question(assistant_message)
    if final_question and not _is_optional_follow_up(final_question):
        return AttentionDecision(
            AttentionState.AMBIGUOUS,
            "unrecognized_trailing_question",
        )

    significant_characters = sum(character.isalnum() for character in assistant_message)
    if significant_characters < 24:
        if local_terminal_evidence:
            return AttentionDecision(
                AttentionState.NEEDS_ATTENTION,
                "validated_local_task_stop",
                AttentionReason.FINISHED,
            )
        return AttentionDecision(AttentionState.AMBIGUOUS, "insufficient_substance")

    return AttentionDecision(
        AttentionState.NEEDS_ATTENTION,
        "substantive_user_facing_stop",
        AttentionReason.FINISHED,
    )

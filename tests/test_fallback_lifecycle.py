from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from pournotify.main import dispatch_codex_payload
from pournotify.models import Category
from pournotify.services.codex_observer import (
    OBSERVER_VERSION,
    CodexRolloutObserver,
    resolve_codex_thread_source,
)
from pournotify.services.diagnostics import NotificationDiagnostics
from pournotify.services.lifecycle_ledger import CodexLifecycleLedger


class CapturingDispatcher:
    def __init__(self):
        self.items = []
        self.traces = []

    def dispatch(self, notification, trace):
        self.items.append(notification)
        self.traces.append(trace)
        return SimpleNamespace(status="attempted")


def payload(turn_id: str, result: str) -> str:
    return json.dumps(
        {
            "type": "agent-turn-complete",
            "thread-id": "fallback-thread",
            "turn-id": turn_id,
            "cwd": r"F:\work\Example",
            "input-messages": ["PRIVATE user context needed only in memory."],
            "last-assistant-message": result,
        }
    )


def rollout_record(record_type, record_payload):
    return json.dumps(
        {
            "timestamp": datetime.now(UTC).isoformat(),
            "type": record_type,
            "payload": record_payload,
        },
        separators=(",", ":"),
    )


@pytest.mark.parametrize(
    ("turn_id", "result", "category"),
    [
        (
            "complete",
            "The requested repository check completed successfully with all results verified.",
            Category.TASK_COMPLETED,
        ),
        (
            "short-complete",
            "37 + 28 + 15 = 80 (37 + 28 = 65; 65 + 15 = 80).",
            Category.TASK_COMPLETED,
        ),
        (
            "input",
            "I need your target environment before I can continue with the deployment.",
            Category.INPUT_REQUIRED,
        ),
        (
            "approval",
            "Formal owner approval is required before I can proceed with deployment.",
            Category.APPROVAL_REQUIRED,
        ),
    ],
)
def test_fallback_routes_supported_lifecycle_states_once(
    tmp_path, turn_id, result, category
):
    dispatcher = CapturingDispatcher()

    assert dispatch_codex_payload(
        SimpleNamespace(dispatcher=dispatcher),
        payload(turn_id, result),
        notify_source="codex_local_fallback",
        lifecycle_ledger=CodexLifecycleLedger(tmp_path / "ledger.sqlite3"),
        observer_version=OBSERVER_VERSION,
    )

    assert [item.category for item in dispatcher.items] == [category]
    assert dispatcher.items[0].title == "Codex Needs Attention · Example"
    assert len(dispatcher.items[0].message) <= 160
    assert result not in dispatcher.items[0].message
    assert dispatcher.traces[0].attention_state == "needs_attention"
    assert dispatcher.traces[0].observer_version == OBSERVER_VERSION
    assert dispatcher.traces[0].dedupe_result == "claimed"


@pytest.mark.parametrize(
    "result",
    [
        "Analysis is still in progress and I am continuing the verification.",
        "Is that surprising?",
        '{"description":"Internal task metadata"}',
    ],
)
def test_fallback_suppresses_working_ambiguous_and_metadata_turns(tmp_path, result):
    dispatcher = CapturingDispatcher()

    assert not dispatch_codex_payload(
        SimpleNamespace(dispatcher=dispatcher),
        payload("suppressed", result),
        notify_source="codex_local_fallback",
        lifecycle_ledger=CodexLifecycleLedger(tmp_path / "ledger.sqlite3"),
        observer_version=OBSERVER_VERSION,
    )

    assert dispatcher.items == []


@pytest.mark.parametrize(
    ("thread_source", "state", "reason"),
    [
        ("subagent", "suppressed_internal", "subagent_thread"),
        ("", "ambiguous", "unverified_thread_source"),
    ],
)
def test_normal_notify_suppresses_non_user_or_unverified_thread_source(
    tmp_path, thread_source, state, reason
):
    dispatcher = CapturingDispatcher()
    diagnostics_path = tmp_path / "diagnostics.jsonl"
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    if thread_source:
        (sessions / "rollout-fallback-thread.jsonl").write_text(
            rollout_record(
                "session_meta",
                {
                    "id": "fallback-thread",
                    "thread_source": thread_source,
                    "cwd": r"F:\work\Example",
                },
            )
            + "\n",
            encoding="utf-8",
        )

    assert not dispatch_codex_payload(
        SimpleNamespace(dispatcher=dispatcher),
        payload(
            "source-filtered",
            "The internal worker completed its assigned verification successfully.",
        ),
        NotificationDiagnostics(diagnostics_path),
        notify_source="ipc",
        lifecycle_ledger=CodexLifecycleLedger(tmp_path / "ledger.sqlite3"),
        thread_source_resolver=lambda thread_id: resolve_codex_thread_source(
            sessions, thread_id
        ),
    )

    record = json.loads(diagnostics_path.read_text(encoding="utf-8"))
    assert dispatcher.items == []
    assert record["attention_state"] == state
    assert record["classification_reason"] == reason
    assert record["codex_thread_source"] == thread_source
    assert record["desktop_attempted"] is False
    assert record["history_attempted"] is False


def test_normal_notify_allows_verified_user_thread_source(tmp_path):
    dispatcher = CapturingDispatcher()
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    (sessions / "rollout-fallback-thread.jsonl").write_text(
        rollout_record(
            "session_meta",
            {
                "id": "fallback-thread",
                "thread_source": "user",
                "cwd": r"F:\work\Example",
            },
        )
        + "\n",
        encoding="utf-8",
    )

    assert dispatch_codex_payload(
        SimpleNamespace(dispatcher=dispatcher),
        payload(
            "verified-user",
            "37 + 28 + 15 = 80",
        ),
        notify_source="ipc",
        lifecycle_ledger=CodexLifecycleLedger(tmp_path / "ledger.sqlite3"),
        thread_source_resolver=lambda thread_id: resolve_codex_thread_source(
            sessions, thread_id
        ),
    )

    assert len(dispatcher.items) == 1
    assert dispatcher.traces[0].codex_thread_source == "user"
    assert dispatcher.traces[0].classification_reason == "validated_local_task_stop"


def test_fallback_diagnostics_store_identity_and_decision_but_not_content(tmp_path):
    dispatcher = CapturingDispatcher()
    diagnostics_path = tmp_path / "diagnostics.jsonl"
    diagnostics = NotificationDiagnostics(diagnostics_path)
    private_result = "PRIVATE final result with enough substance to classify as completed."

    assert dispatch_codex_payload(
        SimpleNamespace(dispatcher=dispatcher),
        payload("diagnostic", private_result),
        diagnostics,
        notify_source="codex_local_fallback",
        lifecycle_ledger=CodexLifecycleLedger(tmp_path / "ledger.sqlite3"),
        observer_version=OBSERVER_VERSION,
    )

    serialized = diagnostics_path.read_text(encoding="utf-8")
    record = json.loads(serialized)
    assert record["thread_id"] == "fallback-thread"
    assert record["turn_id"] == "diagnostic"
    assert record["notify_source"] == "codex_local_fallback"
    assert record["detected_lifecycle"] == "needs_attention"
    assert record["attention_state"] == "needs_attention"
    assert record["attention_reason"] == "finished"
    assert record["classification_reason"] == "substantive_user_facing_stop"
    assert record["detection_reason"] == "substantive_user_facing_stop"
    assert record["observer_version"] == OBSERVER_VERSION
    assert record["dedupe_result"] == "claimed"
    assert "PRIVATE user context" not in serialized
    assert "PRIVATE final result" not in serialized


def test_notify_then_fallback_records_duplicate_without_second_delivery(tmp_path):
    dispatcher = CapturingDispatcher()
    ledger = CodexLifecycleLedger(tmp_path / "ledger.sqlite3")
    diagnostics_path = tmp_path / "diagnostics.jsonl"
    diagnostics = NotificationDiagnostics(diagnostics_path)
    completed = payload(
        "shared-turn",
        "The requested lifecycle check completed successfully with verified results.",
    )

    assert dispatch_codex_payload(
        SimpleNamespace(dispatcher=dispatcher),
        completed,
        diagnostics,
        notify_source="ipc",
        lifecycle_ledger=ledger,
    )
    assert not dispatch_codex_payload(
        SimpleNamespace(dispatcher=dispatcher),
        completed,
        diagnostics,
        notify_source="codex_local_fallback",
        lifecycle_ledger=ledger,
        observer_version=OBSERVER_VERSION,
    )

    records = [json.loads(line) for line in diagnostics_path.read_text().splitlines()]
    assert len(dispatcher.items) == 1
    assert records[-1]["dispatch_status"] == "lifecycle_duplicate"
    assert records[-1]["dedupe_result"] == "already_claimed"
    assert records[-1]["desktop_attempted"] is False
    assert records[-1]["history_attempted"] is False


def test_observation_is_read_only_and_does_not_block_later_delivery(tmp_path):
    dispatcher = CapturingDispatcher()
    ledger = CodexLifecycleLedger(tmp_path / "ledger.sqlite3")
    completed = payload(
        "observation-turn",
        "The requested lifecycle check finished with a verified user-facing result.",
    )

    assert not dispatch_codex_payload(
        SimpleNamespace(dispatcher=dispatcher),
        completed,
        notify_source="observation_ipc",
        observation_only=True,
        lifecycle_ledger=ledger,
    )
    assert dispatch_codex_payload(
        SimpleNamespace(dispatcher=dispatcher),
        completed,
        notify_source="codex_local_fallback",
        lifecycle_ledger=ledger,
        observer_version=OBSERVER_VERSION,
    )

    assert len(dispatcher.items) == 1


@pytest.mark.parametrize("normal_notify_first", [False, True])
def test_rollout_observer_and_normal_notify_share_one_delivery(
    tmp_path, normal_notify_first
):
    dispatcher = CapturingDispatcher()
    window = SimpleNamespace(dispatcher=dispatcher)
    ledger = CodexLifecycleLedger(tmp_path / "ledger.sqlite3")
    diagnostics_path = tmp_path / "diagnostics.jsonl"
    diagnostics = NotificationDiagnostics(diagnostics_path)
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    result = "The real-shaped observer integration task finished with a verified result."
    thread_id = "integration-thread"
    turn_id = "integration-turn"
    external_payload = json.loads(payload(turn_id, result))
    external_payload["thread-id"] = thread_id

    def deliver_fallback(candidate):
        dispatch_codex_payload(
            window,
            json.dumps(candidate),
            diagnostics,
            notify_source="codex_local_fallback",
            lifecycle_ledger=ledger,
            observer_version=OBSERVER_VERSION,
        )

    day = datetime.now(UTC).strftime("%Y/%m/%d")
    rollout = sessions / day / f"rollout-{thread_id}.jsonl"
    rollout.parent.mkdir(parents=True)
    rollout.write_text(
        rollout_record(
            "session_meta",
            {
                "id": thread_id,
                "thread_source": "user",
                "cwd": r"F:\work\Example",
            },
        )
        + "\n",
        encoding="utf-8",
    )
    observer = CodexRolloutObserver(sessions, deliver_fallback, enabled=True)
    source_resolver = lambda candidate_id: resolve_codex_thread_source(
        sessions, candidate_id
    )
    if normal_notify_first:
        assert dispatch_codex_payload(
            window,
            json.dumps(external_payload),
            diagnostics,
            notify_source="ipc",
            lifecycle_ledger=ledger,
            thread_source_resolver=source_resolver,
        )

    records = [
        rollout_record("event_msg", {"type": "task_started", "turn_id": turn_id}),
        rollout_record(
            "turn_context",
            {"turn_id": turn_id, "cwd": r"F:\work\Example"},
        ),
        rollout_record(
            "event_msg",
            {"type": "user_message", "message": "Run the integration check."},
        ),
        rollout_record(
            "event_msg",
            {"type": "agent_message", "phase": "final_answer", "message": result},
        ),
        rollout_record(
            "event_msg",
            {
                "type": "task_complete",
                "turn_id": turn_id,
                "last_agent_message": result,
                "completed_at": datetime.now(UTC).timestamp() + 1,
            },
        ),
    ]
    with rollout.open("a", encoding="utf-8") as stream:
        stream.write("\n".join(records) + "\n")
    observer.poll_once()

    if not normal_notify_first:
        assert not dispatch_codex_payload(
            window,
            json.dumps(external_payload),
            diagnostics,
            notify_source="ipc",
            lifecycle_ledger=ledger,
            thread_source_resolver=source_resolver,
        )

    assert len(dispatcher.items) == 1
    assert dispatcher.items[0].deduplication_id == f"codex:{thread_id}:{turn_id}"
    records = [
        json.loads(line) for line in diagnostics_path.read_text(encoding="utf-8").splitlines()
    ]
    duplicates = [
        record for record in records if record["dispatch_status"] == "lifecycle_duplicate"
    ]
    assert len(duplicates) == 1
    assert duplicates[0]["dedupe_result"] == "already_claimed"
    assert duplicates[0]["notify_source"] == (
        "codex_local_fallback" if normal_notify_first else "ipc"
    )


def test_agent_created_follow_up_short_result_reaches_one_attention_delivery(tmp_path):
    dispatcher = CapturingDispatcher()
    ledger = CodexLifecycleLedger(tmp_path / "ledger.sqlite3")
    sessions = tmp_path / "sessions"
    thread_id = "agent-created-thread"
    turn_id = "follow-up-turn"
    result = "Reminder: Appointment at 3:30 PM."
    delegated_input = "The required appointment time is 3:30 PM."
    delegation = (
        "<codex_delegation>"
        "<source_thread_id>sanitized-source-thread</source_thread_id>"
        f"<input>{delegated_input}</input>"
        "</codex_delegation>"
    )
    rollout = sessions / "2026" / "09" / "01" / f"rollout-{thread_id}.jsonl"
    rollout.parent.mkdir(parents=True)
    rollout.write_text(
        rollout_record(
            "session_meta",
            {
                "id": thread_id,
                "thread_source": "agent_created_thread",
                "cwd": r"F:\work\PourAgenda",
            },
        )
        + "\n",
        encoding="utf-8",
    )
    observer = CodexRolloutObserver(
        sessions,
        lambda candidate: dispatch_codex_payload(
            SimpleNamespace(dispatcher=dispatcher),
            json.dumps(candidate),
            notify_source="codex_local_fallback",
            lifecycle_ledger=ledger,
            observer_version=OBSERVER_VERSION,
        ),
        enabled=True,
    )
    records = [
        rollout_record("event_msg", {"type": "task_started", "turn_id": turn_id}),
        rollout_record(
            "turn_context",
            {"turn_id": turn_id, "cwd": r"F:\work\PourAgenda"},
        ),
        rollout_record(
            "response_item",
            {
                "type": "function_call_output",
                "name": "send_message_to_thread",
                "namespace": "codex_app",
                "output": delegation,
                "internal_chat_message_metadata_passthrough": {"turn_id": turn_id},
            },
        ),
        rollout_record(
            "event_msg",
            {"type": "agent_message", "phase": "final_answer", "message": result},
        ),
        rollout_record(
            "event_msg",
            {
                "type": "task_complete",
                "turn_id": turn_id,
                "last_agent_message": result,
                "completed_at": datetime.now(UTC).timestamp() + 1,
            },
        ),
    ]
    with rollout.open("a", encoding="utf-8") as stream:
        stream.write("\n".join(records) + "\n")
    observer.poll_once()

    assert len(dispatcher.items) == 1
    assert dispatcher.items[0].category is Category.TASK_COMPLETED
    assert dispatcher.items[0].title == "Codex Needs Attention · PourAgenda"
    assert dispatcher.items[0].message == (
        "Task finished and is waiting for your next instruction."
    )
    assert "sanitized-source-thread" not in str(dispatcher.items)

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pournotify.services.codex_observer import (
    CodexRolloutObserver,
    resolve_codex_thread_source,
)

FIXED_NOW = datetime(2026, 8, 30, 5, tzinfo=UTC).timestamp()


@pytest.fixture(autouse=True)
def fixed_observer_clock(monkeypatch):
    monkeypatch.setattr("pournotify.services.codex_observer.time.time", lambda: FIXED_NOW)


def _record(record_type, payload):
    return json.dumps(
        {"timestamp": "2026-08-30T05:00:00.000Z", "type": record_type, "payload": payload},
        separators=(",", ":"),
    )


def _session_meta(thread_id="thread-user", *, thread_source="user", cwd=r"F:\work\App"):
    return _record(
        "session_meta",
        {
            "id": thread_id,
            "thread_source": thread_source,
            "cwd": cwd,
            "cli_version": "0.151.0-alpha.7.1",
        },
    )


def _completed_turn(
    turn_id,
    *,
    prompt="Inspect the repository and report the verified result.",
    result="The repository inspection completed and the requested result was verified.",
    cwd=r"F:\work\App",
    completed_at=4_102_444_800,
):
    return [
        _record("event_msg", {"type": "task_started", "turn_id": turn_id}),
        _record("turn_context", {"turn_id": turn_id, "cwd": cwd}),
        _record("event_msg", {"type": "user_message", "message": prompt}),
        _record(
            "event_msg",
            {"type": "agent_message", "phase": "commentary", "message": "Working."},
        ),
        _record(
            "event_msg",
            {"type": "agent_message", "phase": "final_answer", "message": result},
        ),
        _record(
            "event_msg",
            {
                "type": "task_complete",
                "turn_id": turn_id,
                "last_agent_message": result,
                "completed_at": completed_at,
            },
        ),
    ]


def _completed_item(thread_id, turn_id, item):
    return _record(
        "event_msg",
        {
            "type": "item_completed",
            "thread_id": thread_id,
            "turn_id": turn_id,
            "item": item,
        },
    )


def _response_item(payload):
    return _record("response_item", payload)


def _aborted_turn(turn_id):
    return [
        _record("event_msg", {"type": "task_started", "turn_id": turn_id}),
        _record("turn_context", {"turn_id": turn_id, "cwd": r"F:\work\App"}),
        _record("event_msg", {"type": "user_message", "message": "Run the check."}),
        _record(
            "event_msg",
            {"type": "turn_aborted", "turn_id": turn_id, "reason": "interrupted"},
        ),
    ]


def _write_records(path: Path, records, *, append=False, final_newline=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(records)
    if final_newline:
        text += "\n"
    mode = "a" if append else "w"
    with path.open(mode, encoding="utf-8", newline="") as stream:
        stream.write(text)


def test_thread_source_resolver_reads_matching_session_metadata(tmp_path):
    thread_id = "thread-subagent-safe-id"
    rollout = tmp_path / "2026" / "08" / "30" / f"rollout-{thread_id}.jsonl"
    _write_records(
        rollout,
        [
            _session_meta(thread_id, thread_source="subagent"),
            _response_item(
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "PRIVATE prompt"}],
                }
            ),
        ],
    )

    assert resolve_codex_thread_source(tmp_path, thread_id) == "subagent"
    assert resolve_codex_thread_source(tmp_path, "../invalid") == ""


def test_existing_files_are_baselined_without_historical_replay(tmp_path):
    rollout = tmp_path / "2026" / "08" / "30" / "rollout-existing.jsonl"
    _write_records(
        rollout,
        [
            _session_meta(),
            *_completed_turn("turn-historical", completed_at=FIXED_NOW - 1),
        ],
    )
    emitted = []

    observer = CodexRolloutObserver(tmp_path, emitted.append, enabled=True)
    observer.poll_once()

    assert emitted == []

    _write_records(rollout, _completed_turn("turn-new"), append=True)
    observer.poll_once()

    assert emitted == [
        {
            "type": "agent-turn-complete",
            "thread-id": "thread-user",
            "turn-id": "turn-new",
            "cwd": r"F:\work\App",
            "input-messages": ["Inspect the repository and report the verified result."],
            "last-assistant-message": (
                "The repository inspection completed and the requested result was verified."
            ),
        }
    ]
    metrics = observer.metrics_snapshot()
    assert metrics.baselines == 1
    assert metrics.files_baselined == 1
    assert metrics.candidates_emitted == 1


def test_running_turn_at_baseline_is_hydrated_and_emits_when_completed(tmp_path):
    rollout = tmp_path / "2026" / "08" / "30" / "rollout-running.jsonl"
    turn_id = "turn-running"
    result = "The requested live check completed successfully."
    _write_records(
        rollout,
        [
            _session_meta("thread-running"),
            _record("event_msg", {"type": "task_started", "turn_id": turn_id}),
            _record(
                "turn_context",
                {"turn_id": turn_id, "cwd": r"F:\work\App"},
            ),
            _record(
                "event_msg",
                {"type": "user_message", "message": "Complete the live check."},
            ),
            _record(
                "event_msg",
                {
                    "type": "agent_message",
                    "phase": "commentary",
                    "message": "The live check is still running.",
                },
            ),
        ],
    )
    emitted = []

    observer = CodexRolloutObserver(tmp_path, emitted.append, enabled=True)

    assert emitted == []
    assert observer.metrics_snapshot().active_turns_hydrated == 1

    _write_records(
        rollout,
        [
            _record(
                "event_msg",
                {"type": "agent_message", "phase": "final_answer", "message": result},
            ),
            _record(
                "event_msg",
                {
                    "type": "task_complete",
                    "turn_id": turn_id,
                    "last_agent_message": result,
                },
            ),
        ],
        append=True,
    )
    observer.poll_once()

    assert [(item["thread-id"], item["turn-id"]) for item in emitted] == [
        ("thread-running", turn_id)
    ]


def test_completion_racing_startup_baseline_is_not_absorbed(tmp_path, monkeypatch):
    rollout = tmp_path / "2026" / "08" / "30" / "rollout-race.jsonl"
    result = "The requested startup-race validation finished successfully."
    _write_records(
        rollout,
        [
            _session_meta("thread-race"),
            _record("event_msg", {"type": "task_started", "turn_id": "turn-race"}),
            _record(
                "turn_context",
                {"turn_id": "turn-race", "cwd": r"F:\work\App"},
            ),
            _record("event_msg", {"type": "user_message", "message": "Run the check."}),
            _record(
                "event_msg",
                {"type": "agent_message", "phase": "final_answer", "message": result},
            ),
        ],
    )
    emitted = []
    observer = CodexRolloutObserver(tmp_path, emitted.append)
    real_discover = observer._discover_paths
    appended = False

    def discover_and_complete():
        nonlocal appended
        paths = real_discover()
        if not appended:
            appended = True
            _write_records(
                rollout,
                [
                    _record(
                        "event_msg",
                        {
                            "type": "task_complete",
                            "turn_id": "turn-race",
                            "last_agent_message": result,
                            "completed_at": FIXED_NOW + 1,
                        },
                    )
                ],
                append=True,
            )
        return paths

    monkeypatch.setattr(observer, "_discover_paths", discover_and_complete)
    observer.set_enabled(True)

    assert [candidate["turn-id"] for candidate in emitted] == ["turn-race"]


def test_running_turn_outside_hydration_bound_fails_closed(tmp_path):
    rollout = tmp_path / "2026" / "08" / "30" / "rollout-old-running.jsonl"
    turn_id = "turn-outside-bound"
    result = "This completion lacks bounded startup context."
    _write_records(
        rollout,
        [
            _session_meta("thread-old-running"),
            _record("event_msg", {"type": "task_started", "turn_id": turn_id}),
            _record(
                "turn_context",
                {"turn_id": turn_id, "cwd": r"F:\work\App"},
            ),
            _record(
                "event_msg",
                {"type": "user_message", "message": "Complete the old live check."},
            ),
            _record(
                "event_msg",
                {
                    "type": "agent_message",
                    "phase": "commentary",
                    "message": "x" * 512,
                },
            ),
        ],
    )
    emitted = []

    observer = CodexRolloutObserver(
        tmp_path,
        emitted.append,
        enabled=True,
        max_hydration_bytes=128,
    )
    _write_records(
        rollout,
        [
            _record(
                "event_msg",
                {"type": "agent_message", "phase": "final_answer", "message": result},
            ),
            _record(
                "event_msg",
                {
                    "type": "task_complete",
                    "turn_id": turn_id,
                    "last_agent_message": result,
                },
            ),
        ],
        append=True,
    )
    observer.poll_once()

    assert emitted == []
    assert observer.metrics_snapshot().active_turns_hydrated == 0


def test_new_user_rollout_is_read_from_zero(tmp_path):
    emitted = []
    observer = CodexRolloutObserver(tmp_path, emitted.append, enabled=True)
    rollout = tmp_path / "2026" / "08" / "30" / "rollout-new.jsonl"

    _write_records(rollout, [_session_meta("thread-new"), *_completed_turn("turn-new")])
    observer.poll_once()

    assert [(item["thread-id"], item["turn-id"]) for item in emitted] == [
        ("thread-new", "turn-new")
    ]
    assert observer.metrics_snapshot().files_discovered == 1


def test_current_item_completed_protocol_emits_agent_created_user_task(tmp_path):
    emitted = []
    observer = CodexRolloutObserver(tmp_path, emitted.append, enabled=True)
    rollout = tmp_path / "2026" / "08" / "30" / "rollout-item-completed.jsonl"
    thread_id = "thread-item-completed"
    turn_id = "turn-item-completed"
    result = "The requested current-protocol validation completed successfully."

    _write_records(
        rollout,
        [
            _session_meta(thread_id, thread_source="agent_created_thread"),
            _record("event_msg", {"type": "task_started", "turn_id": turn_id}),
            _record("turn_context", {"turn_id": turn_id, "cwd": r"F:\work\App"}),
            _completed_item(
                thread_id,
                turn_id,
                {
                    "type": "UserMessage",
                    "content": [
                        {"type": "text", "text": "Run the current protocol check."}
                    ],
                },
            ),
            _completed_item(
                thread_id,
                turn_id,
                {"type": "Reasoning", "raw_content": []},
            ),
            _completed_item(
                thread_id,
                turn_id,
                {
                    "type": "AgentMessage",
                    "phase": "final_answer",
                    "content": [{"type": "Text", "text": result}],
                },
            ),
            _record(
                "event_msg",
                {
                    "type": "task_complete",
                    "turn_id": turn_id,
                    "last_agent_message": result,
                    "completed_at": 4_102_444_800,
                },
            ),
        ],
    )

    observer.poll_once()

    assert emitted == [
        {
            "type": "agent-turn-complete",
            "thread-id": thread_id,
            "turn-id": turn_id,
            "cwd": r"F:\work\App",
            "input-messages": ["Run the current protocol check."],
            "last-assistant-message": result,
        }
    ]


def test_current_response_item_protocol_supplies_missing_notify_context(tmp_path):
    emitted = []
    observer = CodexRolloutObserver(tmp_path, emitted.append, enabled=True)
    thread_id = "thread-response-item"
    turn_id = "turn-response-item"
    result = "The requested response-item validation finished with a verified result."
    rollout = tmp_path / "2026" / "08" / "30" / "rollout-response-item.jsonl"
    _write_records(
        rollout,
        [
            _session_meta(thread_id, thread_source="agent_created_thread"),
            _record("event_msg", {"type": "task_started", "turn_id": turn_id}),
            _response_item(
                {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "Sanitized app context."},
                        {
                            "type": "input_text",
                            "text": "Run the response-item validation and report the result.",
                        },
                    ],
                }
            ),
            _record("turn_context", {"turn_id": turn_id, "cwd": r"F:\work\App"}),
            _response_item(
                {
                    "type": "message",
                    "role": "assistant",
                    "phase": "final_answer",
                    "content": [{"type": "output_text", "text": result}],
                }
            ),
            _record(
                "event_msg",
                {
                    "type": "task_complete",
                    "turn_id": turn_id,
                    "last_agent_message": result,
                    "completed_at": 4_102_444_800,
                },
            ),
        ],
    )

    observer.poll_once()

    assert emitted == [
        {
            "type": "agent-turn-complete",
            "thread-id": thread_id,
            "turn-id": turn_id,
            "cwd": r"F:\work\App",
            "input-messages": [
                (
                    "Sanitized app context.\n"
                    "Run the response-item validation and report the result."
                )
            ],
            "last-assistant-message": result,
        }
    ]


def test_codex_app_follow_up_supplies_safe_context_without_raw_output(tmp_path):
    emitted = []
    observer = CodexRolloutObserver(tmp_path, emitted.append, enabled=True)
    thread_id = "thread-follow-up"
    turn_id = "turn-follow-up"
    result = "Reminder: Your appointment is at 3:30 PM."
    delegated_input = "The required appointment time is 3:30 PM."
    delegation = (
        "<codex_delegation>"
        "<source_thread_id>sanitized-source-thread</source_thread_id>"
        f"<input>{delegated_input}</input>"
        "</codex_delegation>"
    )
    rollout = tmp_path / "2026" / "08" / "30" / "rollout-follow-up.jsonl"
    _write_records(
        rollout,
        [
            _session_meta(thread_id, thread_source="agent_created_thread"),
            _record("event_msg", {"type": "task_started", "turn_id": turn_id}),
            _record("turn_context", {"turn_id": turn_id, "cwd": r"F:\work\App"}),
            _response_item(
                {
                    "type": "function_call_output",
                    "name": "send_message_to_thread",
                    "namespace": "codex_app",
                    "output": delegation,
                    "internal_chat_message_metadata_passthrough": {
                        "turn_id": turn_id,
                        "create_time": 4_102_444_799,
                    },
                }
            ),
            _completed_item(
                thread_id,
                turn_id,
                {
                    "type": "FunctionCallOutput",
                    "name": "send_message_to_thread",
                    "namespace": "codex_app",
                    "output": delegation,
                },
            ),
            _response_item(
                {
                    "type": "message",
                    "role": "assistant",
                    "phase": "final_answer",
                    "content": [{"type": "output_text", "text": result}],
                }
            ),
            _record(
                "event_msg",
                {
                    "type": "task_complete",
                    "turn_id": turn_id,
                    "last_agent_message": result,
                    "completed_at": 4_102_444_800,
                },
            ),
        ],
    )

    observer.poll_once()

    assert emitted == [
        {
            "type": "agent-turn-complete",
            "thread-id": thread_id,
            "turn-id": turn_id,
            "cwd": r"F:\work\App",
            "input-messages": [delegated_input],
            "last-assistant-message": result,
        }
    ]
    assert "sanitized-source-thread" not in str(emitted)


def test_subagent_and_aborted_turns_are_suppressed(tmp_path):
    emitted = []
    observer = CodexRolloutObserver(tmp_path, emitted.append, enabled=True)
    subagent = tmp_path / "2026" / "08" / "30" / "rollout-subagent.jsonl"
    user = tmp_path / "2026" / "08" / "30" / "rollout-user.jsonl"

    _write_records(
        subagent,
        [
            _session_meta("thread-subagent", thread_source="subagent"),
            *_completed_turn("turn-subagent"),
        ],
    )
    _write_records(user, [_session_meta(), *_aborted_turn("turn-aborted")])
    observer.poll_once()

    assert emitted == []


def test_partial_line_waits_for_newline_and_read_budget_is_bounded(tmp_path):
    emitted = []
    observer = CodexRolloutObserver(
        tmp_path,
        emitted.append,
        enabled=True,
        max_read_bytes_per_file=128,
        max_read_bytes_per_poll=128,
    )
    rollout = tmp_path / "2026" / "08" / "30" / "rollout-partial.jsonl"
    records = [_session_meta(), *_completed_turn("turn-partial")]
    _write_records(rollout, records[:-1])
    _write_records(rollout, [records[-1]], append=True, final_newline=False)

    previous_bytes = 0
    for _ in range(100):
        observer.poll_once()
        current_bytes = observer.metrics_snapshot().bytes_read
        assert current_bytes - previous_bytes <= 128
        previous_bytes = current_bytes
        if previous_bytes == rollout.stat().st_size:
            break

    assert emitted == []

    with rollout.open("ab") as stream:
        stream.write(b"\n")
    observer.poll_once()

    assert [item["turn-id"] for item in emitted] == ["turn-partial"]


def test_malformed_unknown_and_incomplete_schema_fail_closed(tmp_path):
    emitted = []
    observer = CodexRolloutObserver(tmp_path, emitted.append, enabled=True)
    rollout = tmp_path / "2026" / "08" / "30" / "rollout-malformed.jsonl"
    _write_records(
        rollout,
        [
            _session_meta(),
            "{not-json",
            _record("future_record", {"type": "future_event"}),
            _record(
                "event_msg",
                {
                    "type": "task_complete",
                    "turn_id": "turn-without-start",
                    "last_agent_message": "This must not be delivered.",
                },
            ),
        ],
    )

    observer.poll_once()

    assert emitted == []
    metrics = observer.metrics_snapshot()
    assert metrics.malformed_lines == 1
    assert metrics.schema_rejections >= 1


def test_disable_then_enable_establishes_a_fresh_baseline(tmp_path):
    emitted = []
    observer = CodexRolloutObserver(tmp_path, emitted.append, enabled=True)
    observer.set_enabled(False)
    rollout = tmp_path / "2026" / "08" / "30" / "rollout-disabled.jsonl"
    _write_records(
        rollout,
        [
            _session_meta(),
            *_completed_turn("turn-while-disabled", completed_at=FIXED_NOW - 1),
        ],
    )

    observer.poll_once()
    observer.set_enabled(True)
    observer.poll_once()

    assert emitted == []

    _write_records(rollout, _completed_turn("turn-after-enable"), append=True)
    observer.poll_once()

    assert [item["turn-id"] for item in emitted] == ["turn-after-enable"]
    assert observer.metrics_snapshot().baselines == 2


def test_unavailable_source_is_baselined_when_it_first_appears(tmp_path):
    sessions = tmp_path / "missing"
    emitted = []
    observer = CodexRolloutObserver(sessions, emitted.append, enabled=True)
    rollout = sessions / "2026" / "08" / "30" / "rollout-existing.jsonl"
    _write_records(
        rollout,
        [
            _session_meta(),
            *_completed_turn("turn-before-source", completed_at=FIXED_NOW - 1),
        ],
    )

    observer.poll_once()
    observer.poll_once()

    assert emitted == []
    assert observer.metrics_snapshot().source_errors >= 1


def test_callback_failure_is_contained_and_counted(tmp_path):
    def failing_callback(_payload):
        raise RuntimeError("synthetic callback failure")

    observer = CodexRolloutObserver(tmp_path, failing_callback, enabled=True)
    rollout = tmp_path / "2026" / "08" / "30" / "rollout-callback.jsonl"
    _write_records(rollout, [_session_meta(), *_completed_turn("turn-callback")])

    observer.poll_once()

    metrics = observer.metrics_snapshot()
    assert metrics.candidates_detected == 1
    assert metrics.candidates_emitted == 0
    assert metrics.callback_errors == 1


def test_baseline_stat_failure_retries_without_replaying_other_history(tmp_path, monkeypatch):
    first = tmp_path / "2026" / "08" / "30" / "rollout-first.jsonl"
    second = tmp_path / "2026" / "08" / "30" / "rollout-second.jsonl"
    _write_records(
        first,
        [
            _session_meta("thread-first"),
            *_completed_turn("turn-first", completed_at=FIXED_NOW - 1),
        ],
    )
    _write_records(
        second,
        [
            _session_meta("thread-second"),
            *_completed_turn("turn-second", completed_at=FIXED_NOW - 1),
        ],
    )
    emitted = []
    observer = CodexRolloutObserver(tmp_path, emitted.append)
    real_discover = observer._discover_paths
    first_discovery = True

    def discover_with_one_missing_file():
        nonlocal first_discovery
        paths = real_discover()
        if first_discovery:
            first_discovery = False
            second.unlink()
            return [first, second]
        return paths

    monkeypatch.setattr(observer, "_discover_paths", discover_with_one_missing_file)
    observer.set_enabled(True)
    observer.poll_once()

    assert emitted == []
    assert observer.metrics_snapshot().baselines == 1


def test_late_discovered_historical_rollout_requires_post_baseline_completion(tmp_path):
    emitted = []
    observer = CodexRolloutObserver(tmp_path, emitted.append, enabled=True, clock=lambda: 2_000)
    rollout = tmp_path / "1970" / "01" / "01" / "rollout-late-old.jsonl"
    _write_records(
        rollout,
        [
            _session_meta("thread-late-old"),
            *_completed_turn("turn-late-old", completed_at=1_000),
        ],
    )

    observer.poll_once()

    assert emitted == []


def test_parallel_rollouts_are_tracked_independently(tmp_path):
    emitted = []
    observer = CodexRolloutObserver(tmp_path, emitted.append, enabled=True)
    day = tmp_path / "2026" / "08" / "30"
    _write_records(
        day / "rollout-a.jsonl",
        [_session_meta("thread-a"), *_completed_turn("turn-a")],
    )
    _write_records(
        day / "rollout-b.jsonl",
        [_session_meta("thread-b"), *_completed_turn("turn-b")],
    )
    _write_records(
        day / "rollout-running.jsonl",
        [
            _session_meta("thread-running"),
            _record("event_msg", {"type": "task_started", "turn_id": "turn-running"}),
        ],
    )

    observer.poll_once()

    assert {(item["thread-id"], item["turn-id"]) for item in emitted} == {
        ("thread-a", "turn-a"),
        ("thread-b", "turn-b"),
    }

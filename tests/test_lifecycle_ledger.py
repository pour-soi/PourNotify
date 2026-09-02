import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from pournotify.main import dispatch_codex_payload
from pournotify.services.lifecycle_ledger import (
    CodexLifecycleLedger,
    LifecycleLedgerError,
    lifecycle_key,
)


class CountingDispatcher:
    def __init__(self):
        self.notifications = []

    def dispatch(self, notification, trace):
        self.notifications.append(notification)
        return SimpleNamespace(status="attempted")


def codex_payload(thread_id="thread-a", turn_id="turn-a"):
    return json.dumps({
        "type": "agent-turn-complete",
        "thread-id": thread_id,
        "turn-id": turn_id,
        "cwd": r"F:\work\Example",
        "input-messages": ["Inspect the project and report the result."],
        "last-assistant-message": (
            "The requested project inspection is complete and the verified result is ready."
        ),
    })


def test_lifecycle_identity_includes_thread_and_turn():
    assert lifecycle_key("thread-a", "turn-1") != lifecycle_key("thread-b", "turn-1")


def test_claim_is_persistent_and_preserves_first_source(tmp_path):
    path = tmp_path / "ledger.json"
    first = CodexLifecycleLedger(path)

    assert first.claim("thread-a", "turn-a", "ipc").claimed is True

    restarted = CodexLifecycleLedger(path)
    duplicate = restarted.claim("thread-a", "turn-a", "codex_local_fallback")
    assert duplicate.claimed is False
    assert duplicate.original_source == "ipc"


def test_corrupt_ledger_fails_closed_without_overwriting_it(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_text("not json", encoding="utf-8")
    ledger = CodexLifecycleLedger(path)

    with pytest.raises(LifecycleLedgerError):
        ledger.claim("thread-a", "turn-a", "codex_local_fallback")

    assert path.read_text(encoding="utf-8") == "not json"


def test_corrupt_ledger_suppresses_fallback_but_preserves_normal_notify(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_text("not json", encoding="utf-8")
    ledger = CodexLifecycleLedger(path)
    dispatcher = CountingDispatcher()
    window = SimpleNamespace(dispatcher=dispatcher)

    assert not dispatch_codex_payload(
        window,
        codex_payload("thread-a", "fallback-turn"),
        notify_source="codex_local_fallback",
        lifecycle_ledger=ledger,
    )
    assert dispatch_codex_payload(
        window,
        codex_payload("thread-a", "notify-turn"),
        notify_source="ipc",
        lifecycle_ledger=ledger,
    )
    assert len(dispatcher.notifications) == 1


def test_ledger_is_bounded_to_recent_claims(tmp_path):
    path = tmp_path / "ledger.json"
    ledger = CodexLifecycleLedger(path, max_entries=2)

    for index in range(3):
        assert ledger.claim("thread-a", f"turn-{index}", "ipc").claimed

    with sqlite3.connect(path) as connection:
        entries = [
            row[0]
            for row in connection.execute(
                "SELECT dedupe_key FROM lifecycle_claims ORDER BY sequence_number"
            )
        ]
    assert entries == [
        lifecycle_key("thread-a", "turn-1"),
        lifecycle_key("thread-a", "turn-2"),
    ]


def test_two_live_ledger_instances_share_an_atomic_claim(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    first = CodexLifecycleLedger(path)
    second = CodexLifecycleLedger(path)

    assert first.claim("thread-a", "turn-a", "ipc").claimed is True
    duplicate = second.claim("thread-a", "turn-a", "codex_local_fallback")

    assert duplicate.claimed is False
    assert duplicate.original_source == "ipc"


def test_two_live_ledger_instances_cannot_claim_concurrently(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    ledgers = [CodexLifecycleLedger(path), CodexLifecycleLedger(path)]
    barrier = threading.Barrier(2)

    def claim(index):
        barrier.wait()
        return ledgers[index].claim("thread-a", "turn-a", f"source-{index}")

    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = list(executor.map(claim, range(2)))

    assert sorted(item.claimed for item in claims) == [False, True]


@pytest.mark.parametrize(("thread_id", "turn_id"), [("", "turn"), ("thread", "")])
def test_empty_lifecycle_identity_is_rejected(thread_id, turn_id):
    with pytest.raises(ValueError):
        lifecycle_key(thread_id, turn_id)


@pytest.mark.parametrize(
    "sources",
    [
        ("ipc", "codex_local_fallback"),
        ("codex_local_fallback", "ipc"),
    ],
)
def test_notify_and_fallback_share_exact_once_claim(tmp_path, sources):
    ledger = CodexLifecycleLedger(tmp_path / "ledger.json")
    dispatcher = CountingDispatcher()
    window = SimpleNamespace(dispatcher=dispatcher)

    assert dispatch_codex_payload(
        window, codex_payload(), notify_source=sources[0], lifecycle_ledger=ledger
    )
    assert not dispatch_codex_payload(
        window, codex_payload(), notify_source=sources[1], lifecycle_ledger=ledger
    )
    assert len(dispatcher.notifications) == 1


def test_delayed_notify_is_suppressed_after_ledger_restart(tmp_path):
    path = tmp_path / "ledger.json"
    first_dispatcher = CountingDispatcher()
    assert dispatch_codex_payload(
        SimpleNamespace(dispatcher=first_dispatcher),
        codex_payload(),
        notify_source="codex_local_fallback",
        lifecycle_ledger=CodexLifecycleLedger(path),
    )

    delayed_dispatcher = CountingDispatcher()
    assert not dispatch_codex_payload(
        SimpleNamespace(dispatcher=delayed_dispatcher),
        codex_payload(),
        notify_source="ipc",
        lifecycle_ledger=CodexLifecycleLedger(path),
    )
    assert delayed_dispatcher.notifications == []


def test_same_turn_id_in_different_threads_is_not_a_duplicate(tmp_path):
    ledger = CodexLifecycleLedger(tmp_path / "ledger.json")
    dispatcher = CountingDispatcher()
    window = SimpleNamespace(dispatcher=dispatcher)

    assert dispatch_codex_payload(
        window, codex_payload("thread-a", "same-turn"), lifecycle_ledger=ledger
    )
    assert dispatch_codex_payload(
        window, codex_payload("thread-b", "same-turn"), lifecycle_ledger=ledger
    )
    assert len(dispatcher.notifications) == 2


def test_rate_limited_fallback_releases_claim_for_delayed_notify(tmp_path):
    class RateLimitThenDeliver:
        def __init__(self):
            self.calls = 0
            self.deliveries = 0

        def dispatch(self, notification, trace):
            self.calls += 1
            if self.calls == 1:
                return SimpleNamespace(status="rate_limited")
            self.deliveries += 1
            return SimpleNamespace(status="attempted")

    dispatcher = RateLimitThenDeliver()
    ledger = CodexLifecycleLedger(tmp_path / "ledger.sqlite3")
    retries = []

    assert not dispatch_codex_payload(
        SimpleNamespace(dispatcher=dispatcher),
        codex_payload(),
        notify_source="codex_local_fallback",
        lifecycle_ledger=ledger,
        retry_unattempted=lambda: retries.append(True),
    )
    assert retries == [True]
    assert dispatch_codex_payload(
        SimpleNamespace(dispatcher=dispatcher),
        codex_payload(),
        notify_source="ipc",
        lifecycle_ledger=ledger,
    )
    assert dispatcher.deliveries == 1

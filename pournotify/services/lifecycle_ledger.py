from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..config import app_data_dir

LEDGER_VERSION = 1
DEFAULT_MAX_ENTRIES = 5000


class LifecycleLedgerError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class LifecycleClaim:
    claimed: bool
    key: str
    original_source: str = ""


def lifecycle_key(thread_id: str, turn_id: str) -> str:
    if not thread_id.strip() or not turn_id.strip() or "\0" in thread_id + turn_id:
        raise ValueError("Codex lifecycle identity requires non-empty thread and turn IDs.")
    return f"codex:{thread_id}:{turn_id}"


class CodexLifecycleLedger:
    """Cross-process at-most-once claims shared by notify and fallback sources."""

    def __init__(self, path: Path | None = None, max_entries: int = DEFAULT_MAX_ENTRIES):
        self.path = path or app_data_dir() / "codex-lifecycle-ledger.sqlite3"
        self.max_entries = max(1, max_entries)
        self._lock = threading.Lock()
        self._load_error = ""
        self._initialize()

    @property
    def available(self) -> bool:
        return not self._load_error

    @property
    def load_error(self) -> str:
        return self._load_error

    def claim(self, thread_id: str, turn_id: str, source: str) -> LifecycleClaim:
        key = lifecycle_key(thread_id, turn_id)
        with self._lock:
            if self._load_error:
                raise LifecycleLedgerError(self._load_error)
            try:
                with self._connect() as connection:
                    cursor = connection.execute(
                        "INSERT OR IGNORE INTO lifecycle_claims "
                        "(dedupe_key, source, claimed_at) VALUES (?, ?, ?)",
                        (
                            key,
                            source,
                            datetime.now().astimezone().isoformat(timespec="seconds"),
                        ),
                    )
                    if cursor.rowcount == 0:
                        row = connection.execute(
                            "SELECT source FROM lifecycle_claims WHERE dedupe_key = ?",
                            (key,),
                        ).fetchone()
                        return LifecycleClaim(False, key, str(row[0]) if row else "")
                    connection.execute(
                        "DELETE FROM lifecycle_claims WHERE dedupe_key IN ("
                        "SELECT dedupe_key FROM lifecycle_claims "
                        "ORDER BY sequence_number ASC LIMIT MAX(0, "
                        "(SELECT COUNT(*) FROM lifecycle_claims) - ?)"
                        ")",
                        (self.max_entries,),
                    )
            except sqlite3.Error as error:
                raise LifecycleLedgerError(
                    f"Unable to persist lifecycle claim: {type(error).__name__}"
                ) from error
        return LifecycleClaim(True, key)

    def release(self, thread_id: str, turn_id: str, source: str) -> bool:
        """Release only an unattempted claim owned by the specified intake source."""
        key = lifecycle_key(thread_id, turn_id)
        with self._lock:
            if self._load_error:
                raise LifecycleLedgerError(self._load_error)
            try:
                with self._connect() as connection:
                    cursor = connection.execute(
                        "DELETE FROM lifecycle_claims WHERE dedupe_key = ? AND source = ?",
                        (key, source),
                    )
            except sqlite3.Error as error:
                raise LifecycleLedgerError(
                    f"Unable to release lifecycle claim: {type(error).__name__}"
                ) from error
        return cursor.rowcount == 1

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as connection:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS ledger_metadata "
                    "(schema_version INTEGER NOT NULL)"
                )
                row = connection.execute(
                    "SELECT schema_version FROM ledger_metadata LIMIT 1"
                ).fetchone()
                if row is None:
                    connection.execute(
                        "INSERT INTO ledger_metadata (schema_version) VALUES (?)",
                        (LEDGER_VERSION,),
                    )
                elif row[0] != LEDGER_VERSION:
                    raise LifecycleLedgerError("Unsupported lifecycle ledger schema")
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS lifecycle_claims ("
                    "sequence_number INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "dedupe_key TEXT NOT NULL UNIQUE, "
                    "source TEXT NOT NULL, "
                    "claimed_at TEXT NOT NULL"
                    ")"
                )
        except (OSError, sqlite3.Error, LifecycleLedgerError) as error:
            self._load_error = f"Lifecycle ledger unavailable: {type(error).__name__}"

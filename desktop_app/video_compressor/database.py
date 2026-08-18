from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

from .config import DATABASE_NAME, STATE_DIR_NAME
from .platform_utils import make_hidden, source_birthtime_ns


PENDING = "pending"
PROBING = "probing"
COMPRESSING = "compressing"
VERIFYING = "verifying"
READY_TO_REPLACE = "ready_to_replace"
STAGED_READY = "staged_ready"
COPYING_BACK = "copying_back"
REPLACING = "replacing"
WAITING_REPLACE = "waiting_replace"
COMPLETED = "completed"
SKIPPED_LOW_BITRATE = "skipped_low_bitrate"
BROKEN_SOURCE = "broken_source"
BLOCKED_IN_USE = "blocked_in_use"
FAILED = "failed"

RECOVERABLE_STATUSES = {
    PROBING,
    COMPRESSING,
    VERIFYING,
    READY_TO_REPLACE,
    STAGED_READY,
    COPYING_BACK,
    REPLACING,
    WAITING_REPLACE,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class TaskRecord:
    id: int
    relative_path: str
    status: str
    source_size: int
    source_mtime_ns: int
    source_atime_ns: int
    source_birthtime_ns: Optional[int]
    source_packets: Optional[int]
    source_bitrate: Optional[int]
    source_duration: Optional[float]
    output_size: Optional[int]
    output_packets: Optional[int]
    output_bitrate: Optional[int]
    temp_path: Optional[str]
    temp_external: bool
    error: Optional[str]


class TaskDatabase:
    def __init__(self, source_root: Path):
        self.source_root = source_root.resolve()
        self.state_dir = self.source_root / STATE_DIR_NAME
        self.state_dir.mkdir(parents=True, exist_ok=True)
        make_hidden(self.state_dir)
        self.logs_dir = self.state_dir / "logs"
        self.reports_dir = self.state_dir / "reports"
        self.logs_dir.mkdir(exist_ok=True)
        self.reports_dir.mkdir(exist_ok=True)
        self.path = self.state_dir / DATABASE_NAME
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(str(self.path), timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("PRAGMA synchronous=FULL")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                INSERT OR IGNORE INTO metadata(key, value) VALUES('schema_version', '1');

                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    relative_path TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL DEFAULT 'pending',
                    source_size INTEGER NOT NULL,
                    source_mtime_ns INTEGER NOT NULL,
                    source_atime_ns INTEGER NOT NULL,
                    source_birthtime_ns INTEGER,
                    source_packets INTEGER,
                    source_bitrate INTEGER,
                    source_duration REAL,
                    output_size INTEGER,
                    output_packets INTEGER,
                    output_bitrate INTEGER,
                    temp_path TEXT,
                    temp_external INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
                """
            )

    def register_files(self, paths: Iterable[Path]) -> None:
        now = utc_now()
        with self._connect() as connection:
            for path in paths:
                stat = path.stat()
                relative = path.relative_to(self.source_root).as_posix()
                row = connection.execute(
                    "SELECT * FROM tasks WHERE relative_path = ?", (relative,)
                ).fetchone()
                if row is None:
                    connection.execute(
                        """
                        INSERT INTO tasks(
                            relative_path, status, source_size, source_mtime_ns,
                            source_atime_ns, source_birthtime_ns, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            relative,
                            PENDING,
                            stat.st_size,
                            stat.st_mtime_ns,
                            stat.st_atime_ns,
                            source_birthtime_ns(path),
                            now,
                            now,
                        ),
                    )
                    continue

                completed_match = (
                    row["status"] == COMPLETED
                    and row["output_size"] is not None
                    and stat.st_size == row["output_size"]
                    and stat.st_mtime_ns == row["source_mtime_ns"]
                )
                skipped_match = (
                    row["status"] == SKIPPED_LOW_BITRATE
                    and stat.st_size == row["source_size"]
                    and stat.st_mtime_ns == row["source_mtime_ns"]
                )
                recoverable_match = row["status"] in RECOVERABLE_STATUSES
                if completed_match or skipped_match or recoverable_match:
                    continue

                if stat.st_size != row["source_size"] or stat.st_mtime_ns != row["source_mtime_ns"]:
                    connection.execute(
                        """
                        UPDATE tasks SET
                            status=?, source_size=?, source_mtime_ns=?, source_atime_ns=?,
                            source_birthtime_ns=?, source_packets=NULL, source_bitrate=NULL,
                            source_duration=NULL, output_size=NULL, output_packets=NULL,
                            output_bitrate=NULL, temp_path=NULL, temp_external=0,
                            error=NULL, updated_at=?
                        WHERE id=?
                        """,
                        (
                            PENDING,
                            stat.st_size,
                            stat.st_mtime_ns,
                            stat.st_atime_ns,
                            source_birthtime_ns(path),
                            now,
                            row["id"],
                        ),
                    )

    def _row_to_task(self, row: sqlite3.Row) -> TaskRecord:
        return TaskRecord(
            id=row["id"],
            relative_path=row["relative_path"],
            status=row["status"],
            source_size=row["source_size"],
            source_mtime_ns=row["source_mtime_ns"],
            source_atime_ns=row["source_atime_ns"],
            source_birthtime_ns=row["source_birthtime_ns"],
            source_packets=row["source_packets"],
            source_bitrate=row["source_bitrate"],
            source_duration=row["source_duration"],
            output_size=row["output_size"],
            output_packets=row["output_packets"],
            output_bitrate=row["output_bitrate"],
            temp_path=row["temp_path"],
            temp_external=bool(row["temp_external"]),
            error=row["error"],
        )

    def get(self, task_id: int) -> TaskRecord:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(task_id)
        return self._row_to_task(row)

    def list_tasks(self, statuses: Optional[Iterable[str]] = None) -> list[TaskRecord]:
        with self._connect() as connection:
            if statuses is None:
                rows = connection.execute("SELECT * FROM tasks ORDER BY relative_path").fetchall()
            else:
                status_list = list(statuses)
                if not status_list:
                    return []
                placeholders = ",".join("?" for _ in status_list)
                rows = connection.execute(
                    f"SELECT * FROM tasks WHERE status IN ({placeholders}) ORDER BY relative_path",
                    status_list,
                ).fetchall()
        return [self._row_to_task(row) for row in rows]

    def update(self, task_id: int, status: Optional[str] = None, **fields: Any) -> None:
        if status is not None:
            fields["status"] = status
        fields["updated_at"] = utc_now()
        allowed = {
            "status",
            "source_packets",
            "source_bitrate",
            "source_duration",
            "output_size",
            "output_packets",
            "output_bitrate",
            "temp_path",
            "temp_external",
            "error",
            "attempts",
            "updated_at",
        }
        invalid = set(fields) - allowed
        if invalid:
            raise ValueError(f"unsupported task fields: {sorted(invalid)}")
        assignments = ", ".join(f"{name}=?" for name in fields)
        values = [int(value) if name == "temp_external" else value for name, value in fields.items()]
        values.append(task_id)
        with self._connect() as connection:
            connection.execute(f"UPDATE tasks SET {assignments} WHERE id=?", values)

    def increment_attempts(self, task_id: int) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE tasks SET attempts=attempts+1, updated_at=? WHERE id=?",
                (utc_now(), task_id),
            )

    def counts(self) -> dict[str, int]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*) AS count FROM tasks GROUP BY status"
            ).fetchall()
        return {row["status"]: row["count"] for row in rows}

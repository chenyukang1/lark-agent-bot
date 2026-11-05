"""Durable state for rebuild attempts and their Jenkins outcomes."""

import os
import sqlite3
from contextlib import closing
from pathlib import Path


class BuildTracker:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or os.getenv("BUILD_TRACKER_DB", "logs/builds.sqlite3"))

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute(
            """CREATE TABLE IF NOT EXISTS rebuild_attempts (
                card_message_id TEXT PRIMARY KEY,
                alias TEXT NOT NULL,
                open_id TEXT NOT NULL,
                report_content TEXT NOT NULL,
                alarm_time TEXT NOT NULL,
                source_build_number INTEGER,
                queue_id INTEGER NOT NULL,
                build_number INTEGER,
                build_url TEXT,
                result TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                finished_at TEXT,
                notified_at TEXT
            )"""
        )
        return connection

    def record_queued(
        self, *, card_message_id: str, alias: str, open_id: str,
        report_content: str, alarm_time: str, source_build_number: int | None,
        queue_id: int,
    ) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """INSERT INTO rebuild_attempts
                (card_message_id, alias, open_id, report_content, alarm_time,
                 source_build_number, queue_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (card_message_id, alias, open_id, report_content, alarm_time,
                 source_build_number, queue_id),
            )

    def record_result(
        self, card_message_id: str, *, build_number: int | None,
        build_url: str, result: str,
    ) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """UPDATE rebuild_attempts SET build_number = ?, build_url = ?,
                result = ?, finished_at = CURRENT_TIMESTAMP
                WHERE card_message_id = ?""",
                (build_number, build_url, result, card_message_id),
            )

    def pending(self) -> list[dict]:
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                "SELECT * FROM rebuild_attempts WHERE notified_at IS NULL"
            ).fetchall()
        return [dict(row) for row in rows]

    def mark_notified(self, card_message_id: str) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "UPDATE rebuild_attempts SET notified_at = CURRENT_TIMESTAMP WHERE card_message_id = ?",
                (card_message_id,),
            )

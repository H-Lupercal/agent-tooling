"""Transactional SQLite persistence for canonical collaboration events."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import replace
from pathlib import Path

from agent_harness.models import Event, event_from_json, event_to_json


class EventStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    run_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    event_json TEXT NOT NULL,
                    PRIMARY KEY (run_id, sequence)
                )
                """
            )

    def append(self, event: Event) -> Event:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM events WHERE run_id = ?",
                (event.run_id,),
            ).fetchone()
            if row is None:
                raise RuntimeError("event sequence query returned no row")
            persisted = replace(event, sequence=int(row[0]))
            connection.execute(
                "INSERT INTO events(run_id, sequence, event_json) VALUES (?, ?, ?)",
                (persisted.run_id, persisted.sequence, event_to_json(persisted)),
            )
            connection.commit()
            return persisted
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def replay(self, run_id: str) -> list[Event]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT event_json FROM events WHERE run_id = ? ORDER BY sequence",
                (run_id,),
            ).fetchall()
        return [event_from_json(str(row[0])) for row in rows]

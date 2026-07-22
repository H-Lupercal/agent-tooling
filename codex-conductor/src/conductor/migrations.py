from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 4


MIGRATIONS: dict[int, tuple[str, ...]] = {
    1: (
        """
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            provider TEXT NOT NULL,
            generation INTEGER NOT NULL CHECK (generation >= 0),
            mode TEXT NOT NULL,
            context_json TEXT,
            created_at REAL NOT NULL,
            heartbeat_at REAL NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS leases (
            run_id TEXT PRIMARY KEY REFERENCES runs(run_id) ON DELETE CASCADE,
            owner_id TEXT NOT NULL,
            heartbeat_at REAL NOT NULL,
            expires_at REAL NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS operations (
            operation_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
            idempotency_key TEXT NOT NULL,
            operation TEXT NOT NULL,
            correlation_id TEXT,
            payload_json TEXT NOT NULL,
            created_at REAL NOT NULL,
            UNIQUE (run_id, idempotency_key)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS reservations (
            reservation_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
            task_id TEXT NOT NULL,
            correlation_id TEXT,
            operation TEXT NOT NULL,
            tier TEXT,
            model TEXT,
            estimated_usd REAL NOT NULL CHECK (estimated_usd >= 0),
            state TEXT NOT NULL CHECK (
                state IN ('approved', 'started', 'stopped', 'costed', 'cancelled', 'expired', 'failed')
            ),
            recoverable INTEGER NOT NULL DEFAULT 0 CHECK (recoverable IN (0, 1)),
            recovery_reason TEXT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            expires_at REAL NOT NULL,
            UNIQUE (run_id, task_id),
            UNIQUE (run_id, correlation_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS decisions (
            decision_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
            operation_id TEXT NOT NULL REFERENCES operations(operation_id) ON DELETE CASCADE,
            idempotency_key TEXT NOT NULL,
            reservation_id TEXT REFERENCES reservations(reservation_id) ON DELETE SET NULL,
            allowed INTEGER NOT NULL CHECK (allowed IN (0, 1)),
            rule TEXT NOT NULL,
            message TEXT NOT NULL,
            mode TEXT NOT NULL,
            operation TEXT NOT NULL,
            selected_model TEXT,
            reservation_estimate_usd REAL NOT NULL CHECK (reservation_estimate_usd >= 0),
            savings_eligible INTEGER NOT NULL CHECK (savings_eligible IN (0, 1)),
            created_at REAL NOT NULL,
            UNIQUE (run_id, idempotency_key)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS lifecycle_events (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL,
            run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
            correlation_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            status TEXT,
            occurred_at REAL NOT NULL,
            payload_json TEXT NOT NULL,
            UNIQUE (run_id, event_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS raw_usage (
            usage_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
            source_event_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            parser_version TEXT NOT NULL,
            model TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            measured INTEGER NOT NULL CHECK (measured IN (0, 1)),
            occurred_at REAL NOT NULL,
            UNIQUE (run_id, source_event_id, parser_version)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS costs (
            cost_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
            event_id TEXT NOT NULL,
            correlation_id TEXT NOT NULL,
            usd REAL NOT NULL CHECK (usd >= 0),
            estimated INTEGER NOT NULL CHECK (estimated IN (0, 1)),
            created_at REAL NOT NULL,
            UNIQUE (run_id, event_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS installation_state (
            key TEXT PRIMARY KEY,
            value_json TEXT NOT NULL,
            updated_at REAL NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS legacy_events (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
            event_json TEXT NOT NULL,
            created_at REAL NOT NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS reservations_active_idx ON reservations(run_id, tier, state)",
        "CREATE INDEX IF NOT EXISTS reservations_expiry_idx ON reservations(state, expires_at)",
        "CREATE INDEX IF NOT EXISTS lifecycle_correlation_idx ON lifecycle_events(run_id, correlation_id)",
        "CREATE INDEX IF NOT EXISTS leases_expiry_idx ON leases(expires_at)",
        "CREATE INDEX IF NOT EXISTS legacy_events_run_idx ON legacy_events(run_id, sequence)",
    ),
    2: (
        """
        CREATE TABLE IF NOT EXISTS correlation_aliases (
            run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
            alias TEXT NOT NULL,
            reservation_id TEXT NOT NULL REFERENCES reservations(reservation_id) ON DELETE CASCADE,
            source_event_id TEXT NOT NULL,
            created_at REAL NOT NULL,
            PRIMARY KEY (run_id, alias),
            UNIQUE (run_id, source_event_id)
        )
        """,
        "CREATE INDEX IF NOT EXISTS correlation_alias_reservation_idx ON correlation_aliases(reservation_id)",
    ),
    3: ("DROP TABLE IF EXISTS legacy_events",),
    4: ("ALTER TABLE reservations ADD COLUMN reasoning_effort TEXT",),
}


def apply_migrations(connection: sqlite3.Connection) -> None:
    current = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if current > SCHEMA_VERSION:
        raise RuntimeError(
            f"database schema version {current} is newer than supported {SCHEMA_VERSION}"
        )
    if current == SCHEMA_VERSION:
        return
    connection.execute("BEGIN IMMEDIATE")
    try:
        current = int(connection.execute("PRAGMA user_version").fetchone()[0])
        for version in range(current + 1, SCHEMA_VERSION + 1):
            for statement in MIGRATIONS[version]:
                connection.execute(statement)
            connection.execute(f"PRAGMA user_version = {version}")
        connection.commit()
    except BaseException:
        connection.rollback()
        raise

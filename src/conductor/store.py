from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from conductor.errors import StateError, StoreBusyError
from conductor.migrations import SCHEMA_VERSION, apply_migrations
from conductor.schemas import (
    Decision,
    LifecycleEvent,
    OperatingMode,
    OperationName,
    Reservation,
    ReservationState,
)


_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_ACTIVE_STATES = (ReservationState.APPROVED.value, ReservationState.STARTED.value)


@dataclass(frozen=True)
class ReservationRequest:
    run_id: str
    task_id: str
    correlation_id: str | None
    idempotency_key: str
    operation: str
    tier: str
    model: str
    estimated_usd: float
    ttl_seconds: int
    generation: int
    mode: str

    def __post_init__(self) -> None:
        for name in ("run_id", "task_id", "idempotency_key", "tier"):
            value = getattr(self, name)
            if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
                raise ValueError(f"{name} is not a valid bounded identifier")
        if self.correlation_id is not None and not _IDENTIFIER.fullmatch(
            self.correlation_id
        ):
            raise ValueError("correlation_id is not a valid bounded identifier")
        OperationName(self.operation)
        OperatingMode(self.mode)
        if not isinstance(self.model, str) or not 1 <= len(self.model) <= 256:
            raise ValueError("model must be a bounded string")
        if not math.isfinite(self.estimated_usd) or self.estimated_usd < 0:
            raise ValueError("estimated_usd must be finite and nonnegative")
        if not isinstance(self.ttl_seconds, int) or self.ttl_seconds < 1:
            raise ValueError("ttl_seconds must be positive")
        if not isinstance(self.generation, int) or self.generation < 1:
            raise ValueError("generation must be positive")


@dataclass(frozen=True)
class ReservationSnapshot:
    active_by_tier: dict[str, int]
    reserved_usd: float
    spent_usd: float


@dataclass(frozen=True)
class DecisionSpec:
    allowed: bool
    rule: str
    message: str
    selected_model: str | None = None
    savings_eligible: bool = False


class Store:
    def __init__(
        self,
        path: Path,
        *,
        busy_timeout_ms: int = 2_000,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if busy_timeout_ms < 1 or busy_timeout_ms > 30_000:
            raise ValueError("busy_timeout_ms must be in 1..30000")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.busy_timeout_ms = busy_timeout_ms
        self._clock = clock
        self._initialize()

    def _initialize(self) -> None:
        last_error: sqlite3.OperationalError | None = None
        for attempt in range(3):
            connection = self._connect()
            try:
                connection.execute("PRAGMA journal_mode = WAL").fetchone()
                apply_migrations(connection)
                return
            except sqlite3.OperationalError as exc:
                last_error = exc
                if not _is_locked(exc) or attempt == 2:
                    raise StoreBusyError(
                        f"cannot initialize conductor store: {exc}"
                    ) from exc
                time.sleep(0.02 * (attempt + 1))
            finally:
                connection.close()
        raise StoreBusyError(f"cannot initialize conductor store: {last_error}")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=self.busy_timeout_ms / 1_000,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
        return connection

    @contextmanager
    def _reader(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except sqlite3.OperationalError as exc:
            connection.rollback()
            if _is_locked(exc):
                raise StoreBusyError(
                    f"conductor store remained locked for {self.busy_timeout_ms}ms"
                ) from exc
            raise StateError(f"conductor store operation failed: {exc}") from exc
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def schema_version(self) -> int:
        with self._reader() as connection:
            return int(connection.execute("PRAGMA user_version").fetchone()[0])

    def journal_mode(self) -> str:
        with self._reader() as connection:
            return str(connection.execute("PRAGMA journal_mode").fetchone()[0])

    def foreign_keys_enabled(self) -> bool:
        with self._reader() as connection:
            return bool(connection.execute("PRAGMA foreign_keys").fetchone()[0])

    def table_names(self) -> set[str]:
        with self._reader() as connection:
            rows = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        return {str(row[0]) for row in rows if not str(row[0]).startswith("sqlite_")}

    def create_run(
        self,
        run_id: str,
        *,
        provider: str,
        generation: int,
        mode: str,
        lease_seconds: int = 300,
        owner_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        validate_identifier(run_id, "run_id")
        if generation < 0 or lease_seconds < 1:
            raise ValueError(
                "generation must be nonnegative and lease_seconds must be positive"
            )
        now = self._clock()
        with self._transaction() as connection:
            connection.execute(
                """
                INSERT INTO runs (
                    run_id, provider, generation, mode, context_json, created_at, heartbeat_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    provider = excluded.provider,
                    generation = excluded.generation,
                    mode = excluded.mode,
                    context_json = excluded.context_json,
                    heartbeat_at = excluded.heartbeat_at
                """,
                (
                    run_id,
                    provider,
                    generation,
                    mode,
                    _json(context) if context is not None else None,
                    now,
                    now,
                ),
            )
            connection.execute(
                """
                INSERT INTO leases (run_id, owner_id, heartbeat_at, expires_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    owner_id = excluded.owner_id,
                    heartbeat_at = excluded.heartbeat_at,
                    expires_at = excluded.expires_at
                """,
                (run_id, owner_id or f"pid-{os.getpid()}", now, now + lease_seconds),
            )

    def heartbeat_run(self, run_id: str, *, lease_seconds: int = 300) -> None:
        now = self._clock()
        with self._transaction() as connection:
            updated = connection.execute(
                """
                UPDATE leases SET heartbeat_at = ?, expires_at = ? WHERE run_id = ?
                """,
                (now, now + lease_seconds, run_id),
            ).rowcount
            connection.execute(
                "UPDATE runs SET heartbeat_at = ? WHERE run_id = ?",
                (now, run_id),
            )
            if updated != 1:
                raise StateError(f"run lease does not exist: {run_id}")

    def reserve(
        self,
        request: ReservationRequest,
        *,
        concurrency_cap: int,
        budget_cap: float,
    ) -> Decision:
        if concurrency_cap < 0:
            raise ValueError("concurrency_cap must be nonnegative")
        if not math.isfinite(budget_cap) or budget_cap < 0:
            raise ValueError("budget_cap must be finite and nonnegative")

        def evaluate(snapshot: ReservationSnapshot) -> DecisionSpec:
            if snapshot.active_by_tier.get(request.tier, 0) >= concurrency_cap:
                return DecisionSpec(
                    False, "CONCURRENCY_CAP", "reservation concurrency cap reached"
                )
            projected = (
                snapshot.spent_usd + snapshot.reserved_usd + request.estimated_usd
            )
            if projected > budget_cap + 1e-12:
                return DecisionSpec(
                    False, "BUDGET_CAP", "reservation budget cap reached"
                )
            return DecisionSpec(True, "ALLOW", "reservation approved")

        return self.decide_and_reserve(request, evaluate)

    def decide_and_reserve(
        self,
        request: ReservationRequest,
        evaluator: Callable[[ReservationSnapshot], DecisionSpec],
    ) -> Decision:
        now = self._clock()
        with self._transaction() as connection:
            self._expire_reservations(connection, now)
            existing = connection.execute(
                "SELECT * FROM decisions WHERE run_id = ? AND idempotency_key = ?",
                (request.run_id, request.idempotency_key),
            ).fetchone()
            if existing is not None:
                return _decision_from_row(existing)

            run = connection.execute(
                "SELECT generation FROM runs WHERE run_id = ?",
                (request.run_id,),
            ).fetchone()
            if run is None:
                raise StateError(f"run does not exist: {request.run_id}")

            operation_id = _new_id("operation")
            connection.execute(
                """
                INSERT INTO operations (
                    operation_id, run_id, idempotency_key, operation,
                    correlation_id, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    operation_id,
                    request.run_id,
                    request.idempotency_key,
                    request.operation,
                    request.correlation_id,
                    _json(request.__dict__),
                    now,
                ),
            )

            if int(run["generation"]) != request.generation:
                spec = DecisionSpec(
                    False, "STALE_GENERATION", "run generation does not match"
                )
            else:
                lease = connection.execute(
                    "SELECT expires_at FROM leases WHERE run_id = ?",
                    (request.run_id,),
                ).fetchone()
                if lease is None or float(lease["expires_at"]) <= now:
                    spec = DecisionSpec(
                        False, "RUN_LEASE_EXPIRED", "run lease is not active"
                    )
                elif (
                    request.correlation_id is not None
                    and connection.execute(
                        "SELECT 1 FROM reservations WHERE run_id = ? AND correlation_id = ?",
                        (request.run_id, request.correlation_id),
                    ).fetchone()
                ):
                    spec = DecisionSpec(
                        False,
                        "DUPLICATE_CORRELATION",
                        "correlation id already has a reservation",
                    )
                elif connection.execute(
                    "SELECT 1 FROM reservations WHERE run_id = ? AND task_id = ?",
                    (request.run_id, request.task_id),
                ).fetchone():
                    spec = DecisionSpec(
                        False,
                        "DUPLICATE_RESERVATION",
                        "task already has a reservation",
                    )
                else:
                    spec = evaluator(self._snapshot(connection, request.run_id))

            reservation_id: str | None = None
            if spec.allowed:
                reservation_id = _new_id("reservation")
                connection.execute(
                    """
                    INSERT INTO reservations (
                        reservation_id, run_id, task_id, correlation_id, operation,
                        tier, model, estimated_usd, state, recoverable,
                        recovery_reason, created_at, updated_at, expires_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'approved', 0, NULL, ?, ?, ?)
                    """,
                    (
                        reservation_id,
                        request.run_id,
                        request.task_id,
                        request.correlation_id,
                        request.operation,
                        request.tier,
                        request.model,
                        request.estimated_usd,
                        now,
                        now,
                        now + request.ttl_seconds,
                    ),
                )

            decision_id = _new_id("decision")
            connection.execute(
                """
                INSERT INTO decisions (
                    decision_id, run_id, operation_id, idempotency_key,
                    reservation_id, allowed, rule, message, mode, operation,
                    selected_model, reservation_estimate_usd, savings_eligible, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision_id,
                    request.run_id,
                    operation_id,
                    request.idempotency_key,
                    reservation_id,
                    int(spec.allowed),
                    spec.rule,
                    spec.message,
                    request.mode,
                    request.operation,
                    spec.selected_model,
                    request.estimated_usd,
                    int(spec.savings_eligible),
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM decisions WHERE decision_id = ?",
                (decision_id,),
            ).fetchone()
            return _decision_from_row(row)

    def _snapshot(
        self, connection: sqlite3.Connection, run_id: str
    ) -> ReservationSnapshot:
        rows = connection.execute(
            """
            SELECT tier, COUNT(*) AS count
            FROM reservations
            WHERE run_id = ? AND state IN ('approved', 'started')
            GROUP BY tier
            """,
            (run_id,),
        ).fetchall()
        reserved = connection.execute(
            """
            SELECT COALESCE(SUM(estimated_usd), 0.0)
            FROM reservations
            WHERE run_id = ? AND state IN ('approved', 'started')
            """,
            (run_id,),
        ).fetchone()[0]
        spent = connection.execute(
            "SELECT COALESCE(SUM(usd), 0.0) FROM costs WHERE run_id = ?",
            (run_id,),
        ).fetchone()[0]
        return ReservationSnapshot(
            active_by_tier={str(row["tier"]): int(row["count"]) for row in rows},
            reserved_usd=float(reserved),
            spent_usd=float(spent),
        )

    def _expire_reservations(self, connection: sqlite3.Connection, now: float) -> None:
        connection.execute(
            """
            UPDATE reservations
            SET state = 'expired', updated_at = ?, recoverable = 0,
                recovery_reason = NULL
            WHERE state IN ('approved', 'started') AND expires_at <= ?
            """,
            (now, now),
        )

    def reserved_count(
        self, *, run_id: str | None = None, tier: str | None = None
    ) -> int:
        clauses = ["state IN ('approved', 'started')"]
        params: list[object] = []
        if run_id is not None:
            clauses.append("run_id = ?")
            params.append(run_id)
        if tier is not None:
            clauses.append("tier = ?")
            params.append(tier)
        with self._reader() as connection:
            row = connection.execute(
                f"SELECT COUNT(*) FROM reservations WHERE {' AND '.join(clauses)}",
                params,
            ).fetchone()
        return int(row[0])

    def decision_count(self, *, run_id: str | None = None) -> int:
        sql = "SELECT COUNT(*) FROM decisions"
        params: tuple[object, ...] = ()
        if run_id is not None:
            sql += " WHERE run_id = ?"
            params = (run_id,)
        with self._reader() as connection:
            return int(connection.execute(sql, params).fetchone()[0])

    def reservation(self, key: str, *, run_id: str | None = None) -> Reservation:
        clauses = ["(reservation_id = ? OR task_id = ? OR correlation_id = ?)"]
        params: list[object] = [key, key, key]
        if run_id is not None:
            clauses.append("run_id = ?")
            params.append(run_id)
        with self._reader() as connection:
            row = connection.execute(
                f"SELECT * FROM reservations WHERE {' AND '.join(clauses)} ORDER BY created_at DESC LIMIT 1",
                params,
            ).fetchone()
        if row is None:
            raise StateError(f"reservation not found: {key}")
        return _reservation_from_row(row)

    def record_lifecycle(self, event: LifecycleEvent) -> Reservation:
        now = self._clock()
        occurred_at = event.occurred_at.timestamp()
        with self._transaction() as connection:
            if (
                connection.execute(
                    "SELECT 1 FROM runs WHERE run_id = ?",
                    (event.run_id,),
                ).fetchone()
                is None
            ):
                raise StateError(f"run does not exist: {event.run_id}")
            inserted = connection.execute(
                """
                INSERT OR IGNORE INTO lifecycle_events (
                    event_id, run_id, correlation_id, kind, status, occurred_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.run_id,
                    event.correlation_id,
                    event.kind.value,
                    event.status,
                    occurred_at,
                    _json(event.model_dump(mode="json")),
                ),
            ).rowcount
            if inserted == 0:
                return self._reservation_in_transaction(
                    connection,
                    event.run_id,
                    event.correlation_id,
                )

            row = connection.execute(
                "SELECT * FROM reservations WHERE run_id = ? AND correlation_id = ?",
                (event.run_id, event.correlation_id),
            ).fetchone()
            if row is None:
                state = _state_for_orphan(event.kind.value)
                reason = f"{event.kind.value} before reservation"
                reservation_id = _new_id("reservation")
                connection.execute(
                    """
                    INSERT INTO reservations (
                        reservation_id, run_id, task_id, correlation_id, operation,
                        tier, model, estimated_usd, state, recoverable,
                        recovery_reason, created_at, updated_at, expires_at
                    ) VALUES (?, ?, ?, ?, 'spawn', NULL, NULL, 0.0, ?, 1, ?, ?, ?, ?)
                    """,
                    (
                        reservation_id,
                        event.run_id,
                        event.correlation_id,
                        event.correlation_id,
                        state,
                        reason,
                        now,
                        now,
                        now + 300,
                    ),
                )
            else:
                state, recoverable, reason = _transition(
                    str(row["state"]),
                    bool(row["recoverable"]),
                    row["recovery_reason"],
                    event.kind.value,
                )
                connection.execute(
                    """
                    UPDATE reservations
                    SET state = ?, recoverable = ?, recovery_reason = ?, updated_at = ?
                    WHERE reservation_id = ?
                    """,
                    (state, int(recoverable), reason, now, row["reservation_id"]),
                )

            if event.usage is not None:
                usage = event.usage
                connection.execute(
                    """
                    INSERT OR IGNORE INTO raw_usage (
                        run_id, source_event_id, provider, parser_version, model,
                        payload_json, measured, occurred_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.run_id,
                        usage.source_event_id,
                        usage.provider.value,
                        usage.parser_version,
                        usage.model,
                        _json(usage.model_dump(mode="json")),
                        int(usage.measured),
                        usage.occurred_at.timestamp(),
                    ),
                )
            if event.cost_usd is not None:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO costs (
                        run_id, event_id, correlation_id, usd, estimated, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.run_id,
                        event.event_id,
                        event.correlation_id,
                        event.cost_usd,
                        int(bool(event.estimated)),
                        now,
                    ),
                )
            return self._reservation_in_transaction(
                connection,
                event.run_id,
                event.correlation_id,
            )

    def _reservation_in_transaction(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        correlation_id: str,
    ) -> Reservation:
        row = connection.execute(
            "SELECT * FROM reservations WHERE run_id = ? AND correlation_id = ?",
            (run_id, correlation_id),
        ).fetchone()
        if row is None:
            raise StateError(f"reservation not found for correlation: {correlation_id}")
        return _reservation_from_row(row)

    def cost_record_count(self, *, event_id: str) -> int:
        with self._reader() as connection:
            return int(
                connection.execute(
                    "SELECT COUNT(*) FROM costs WHERE event_id = ?",
                    (event_id,),
                ).fetchone()[0]
            )

    def gc_candidates(self, *, older_than: float) -> list[str]:
        now = self._clock()
        with self._reader() as connection:
            rows = connection.execute(
                """
                SELECT runs.run_id
                FROM runs
                LEFT JOIN leases ON leases.run_id = runs.run_id AND leases.expires_at > ?
                WHERE runs.heartbeat_at < ? AND leases.run_id IS NULL
                ORDER BY runs.run_id
                """,
                (now, older_than),
            ).fetchall()
        return [str(row["run_id"]) for row in rows]

    def append_legacy_event(self, run_id: str, event: dict[str, Any]) -> None:
        validate_identifier(run_id, "run_id")
        now = self._clock()
        record = {"v": SCHEMA_VERSION, "ts": now, **event}
        with self._transaction() as connection:
            connection.execute(
                """
                INSERT INTO runs (
                    run_id, provider, generation, mode, context_json, created_at, heartbeat_at
                ) VALUES (?, 'legacy', 0, 'observe', NULL, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET heartbeat_at = excluded.heartbeat_at
                """,
                (run_id, now, now),
            )
            connection.execute(
                "INSERT INTO legacy_events (run_id, event_json, created_at) VALUES (?, ?, ?)",
                (run_id, _json(record), now),
            )

    def read_legacy_events(self, run_id: str) -> list[dict[str, Any]]:
        with self._reader() as connection:
            rows = connection.execute(
                "SELECT event_json FROM legacy_events WHERE run_id = ? ORDER BY sequence",
                (run_id,),
            ).fetchall()
        events: list[dict[str, Any]] = []
        for row in rows:
            try:
                value = json.loads(row["event_json"])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                events.append(value)
        return events

    def latest_run_id(self) -> str | None:
        with self._reader() as connection:
            row = connection.execute(
                "SELECT run_id FROM runs ORDER BY heartbeat_at DESC, run_id DESC LIMIT 1"
            ).fetchone()
        return None if row is None else str(row["run_id"])


def _decision_from_row(row: sqlite3.Row) -> Decision:
    return Decision(
        decision_id=row["decision_id"],
        allowed=bool(row["allowed"]),
        rule=row["rule"],
        message=row["message"],
        mode=row["mode"],
        operation=row["operation"],
        selected_model=row["selected_model"],
        reservation_estimate_usd=float(row["reservation_estimate_usd"]),
        savings_eligible=bool(row["savings_eligible"]),
        reservation_id=row["reservation_id"],
        created_at=datetime.fromtimestamp(float(row["created_at"]), UTC),
    )


def _reservation_from_row(row: sqlite3.Row) -> Reservation:
    return Reservation(
        reservation_id=row["reservation_id"],
        run_id=row["run_id"],
        task_id=row["task_id"],
        operation=row["operation"],
        tier=row["tier"],
        model=row["model"],
        estimated_usd=float(row["estimated_usd"]),
        state=row["state"],
        correlation_id=row["correlation_id"],
        recoverable=bool(row["recoverable"]),
        recovery_reason=row["recovery_reason"],
        created_at=datetime.fromtimestamp(float(row["created_at"]), UTC),
        updated_at=datetime.fromtimestamp(float(row["updated_at"]), UTC),
        expires_at=datetime.fromtimestamp(float(row["expires_at"]), UTC),
    )


def _transition(
    state: str,
    recoverable: bool,
    reason: str | None,
    kind: str,
) -> tuple[str, bool, str | None]:
    if kind == "start":
        if state == "approved":
            return "started", False, None
        if state in {"stopped", "costed"}:
            return state, False, None
        return state, recoverable, reason
    if kind == "stop":
        if state == "approved":
            return "stopped", True, "stop before start"
        if state == "started":
            return "stopped", False, None
        if state == "costed":
            return state, False, None
        return state, recoverable, reason
    if kind == "cost":
        if state == "stopped":
            return "costed", recoverable, reason
        if state in {"approved", "started"}:
            return "costed", True, "cost before stop"
        return state, recoverable, reason
    if kind == "cancel":
        return "cancelled", False, None
    if kind == "fail":
        return "failed", False, None
    return state, recoverable, reason


def _state_for_orphan(kind: str) -> str:
    return {
        "start": "started",
        "stop": "stopped",
        "cost": "costed",
        "cancel": "cancelled",
        "fail": "failed",
    }[kind]


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def validate_identifier(value: str, name: str) -> None:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{name} is not a valid bounded identifier")


def _is_locked(error: sqlite3.OperationalError) -> bool:
    message = str(error).lower()
    return "locked" in message or "busy" in message

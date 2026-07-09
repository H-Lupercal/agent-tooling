from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import tomllib
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from toolbelt.errors import ApplyError, ValidationError
from toolbelt.paths import repository_identity, resolve_owned_path
from pydantic import ValidationError as PydanticValidationError

from toolbelt.schemas import DeclarationV2, TransactionState


STATE_SCHEMA_VERSION = 1
_TRANSITIONS: dict[TransactionState, frozenset[TransactionState]] = {
    TransactionState.PLANNED: frozenset({TransactionState.PREFLIGHT, TransactionState.INTERRUPTED}),
    TransactionState.PREFLIGHT: frozenset(
        {TransactionState.APPLYING, TransactionState.ROLLING_BACK, TransactionState.INTERRUPTED}
    ),
    TransactionState.APPLYING: frozenset(
        {TransactionState.VERIFYING, TransactionState.ROLLING_BACK, TransactionState.INTERRUPTED}
    ),
    TransactionState.VERIFYING: frozenset(
        {TransactionState.SUCCEEDED, TransactionState.ROLLING_BACK, TransactionState.INTERRUPTED}
    ),
    TransactionState.ROLLING_BACK: frozenset(
        {TransactionState.ROLLED_BACK, TransactionState.ROLLBACK_FAILED, TransactionState.INTERRUPTED}
    ),
    TransactionState.INTERRUPTED: frozenset(
        {TransactionState.VERIFYING, TransactionState.ROLLING_BACK}
    ),
    TransactionState.SUCCEEDED: frozenset(),
    TransactionState.ROLLED_BACK: frozenset(),
    TransactionState.ROLLBACK_FAILED: frozenset(),
}


class StateStore:
    def __init__(self, path: str | Path, *, busy_timeout_ms: int = 5_000) -> None:
        if not 1 <= busy_timeout_ms <= 30_000:
            raise ValueError("busy_timeout_ms must be in 1..30000")
        self.path = Path(path)
        if self.path.is_symlink():
            raise ValidationError("state database must not be a symbolic link")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.busy_timeout_ms = busy_timeout_ms
        self._initialize()

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

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            connection.execute("PRAGMA journal_mode = WAL").fetchone()
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version not in {0, STATE_SCHEMA_VERSION}:
                raise ValidationError(f"unsupported Toolbelt state schema: {version}")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS transactions (
                    transaction_id TEXT PRIMARY KEY,
                    plan_id TEXT NOT NULL,
                    repository_identity TEXT NOT NULL,
                    state TEXT NOT NULL,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS actions (
                    transaction_id TEXT NOT NULL REFERENCES transactions(transaction_id) ON DELETE CASCADE,
                    action_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (transaction_id, action_id),
                    UNIQUE (transaction_id, sequence)
                );
                CREATE TABLE IF NOT EXISTS command_results (
                    result_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    transaction_id TEXT NOT NULL REFERENCES transactions(transaction_id) ON DELETE CASCADE,
                    action_id TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    argv_json TEXT NOT NULL,
                    returncode INTEGER,
                    stdout TEXT NOT NULL,
                    stderr TEXT NOT NULL,
                    duration_seconds REAL NOT NULL,
                    timed_out INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS backups (
                    backup_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    transaction_id TEXT NOT NULL REFERENCES transactions(transaction_id) ON DELETE CASCADE,
                    relative_path TEXT NOT NULL,
                    backup_path TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    restored INTEGER NOT NULL DEFAULT 0,
                    UNIQUE (transaction_id, relative_path)
                );
                CREATE TABLE IF NOT EXISTS recovery_records (
                    recovery_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    transaction_id TEXT NOT NULL REFERENCES transactions(transaction_id) ON DELETE CASCADE,
                    status TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_transactions_state ON transactions(state);
                CREATE INDEX IF NOT EXISTS idx_commands_transaction ON command_results(transaction_id);
                """
            )
            connection.execute(f"PRAGMA user_version = {STATE_SCHEMA_VERSION}")
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except sqlite3.OperationalError as exc:
            connection.rollback()
            raise ApplyError(f"state database operation failed: {exc}") from exc
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @contextmanager
    def _reader(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
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

    def begin_transaction(
        self,
        *,
        plan_id: str,
        repository_identity: str,
        transaction_id: str | None = None,
    ) -> str:
        _validate_digest(plan_id, "plan_id")
        _validate_digest(repository_identity, "repository_identity")
        selected_id = transaction_id or f"tx-{uuid.uuid4().hex}"
        if not selected_id or len(selected_id) > 128 or any(c in selected_id for c in "/\\\0"):
            raise ValueError("transaction_id must be a bounded identifier")
        now = _now()
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO transactions (
                    transaction_id, plan_id, repository_identity, state, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    selected_id,
                    plan_id,
                    repository_identity,
                    TransactionState.PLANNED.value,
                    now,
                    now,
                ),
            )
        return selected_id

    def transaction_count(self) -> int:
        with self._reader() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0])

    def get_transaction(self, transaction_id: str) -> dict[str, Any] | None:
        with self._reader() as connection:
            row = connection.execute(
                "SELECT * FROM transactions WHERE transaction_id = ?", (transaction_id,)
            ).fetchone()
        return None if row is None else dict(row)

    def incomplete_transactions(self) -> list[dict[str, Any]]:
        terminal = (
            TransactionState.SUCCEEDED.value,
            TransactionState.ROLLED_BACK.value,
            TransactionState.ROLLBACK_FAILED.value,
        )
        with self._reader() as connection:
            rows = connection.execute(
                "SELECT * FROM transactions WHERE state NOT IN (?, ?, ?) ORDER BY created_at",
                terminal,
            ).fetchall()
        return [dict(row) for row in rows]

    def set_transaction_state(
        self,
        transaction_id: str,
        state: TransactionState | str,
        *,
        error: str | None = None,
    ) -> None:
        destination = TransactionState(state)
        if error is not None and len(error) > 4096:
            error = error[:4096]
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT state FROM transactions WHERE transaction_id = ?", (transaction_id,)
            ).fetchone()
            if row is None:
                raise ValueError(f"unknown transaction: {transaction_id}")
            source = TransactionState(str(row["state"]))
            if destination not in _TRANSITIONS[source]:
                raise ValueError(
                    f"invalid transaction transition: {source.value} -> {destination.value}"
                )
            connection.execute(
                "UPDATE transactions SET state = ?, error = ?, updated_at = ? WHERE transaction_id = ?",
                (destination.value, error, _now(), transaction_id),
            )

    def record_action(
        self,
        transaction_id: str,
        action_id: str,
        *,
        sequence: int,
        state: str,
        payload: dict[str, Any],
    ) -> None:
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO actions (
                    transaction_id, action_id, sequence, state, payload_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(transaction_id, action_id) DO UPDATE SET
                    state = excluded.state,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (transaction_id, action_id, sequence, state, _json(payload), _now()),
            )

    def record_command(
        self,
        transaction_id: str,
        action_id: str,
        *,
        phase: str,
        argv: tuple[str, ...],
        returncode: int | None,
        stdout: str,
        stderr: str,
        duration_seconds: float,
        timed_out: bool,
    ) -> None:
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO command_results (
                    transaction_id, action_id, phase, argv_json, returncode,
                    stdout, stderr, duration_seconds, timed_out, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    transaction_id,
                    action_id,
                    phase,
                    _json(argv),
                    returncode,
                    stdout[:65536],
                    stderr[:65536],
                    duration_seconds,
                    int(timed_out),
                    _now(),
                ),
            )

    def record_recovery(self, transaction_id: str, status: str, detail: str) -> None:
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO recovery_records (transaction_id, status, detail, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (transaction_id, status, detail[:4096], _now()),
            )

    def record_backup(
        self,
        transaction_id: str,
        relative_path: str,
        *,
        backup_path: str,
        sha256_digest: str,
    ) -> None:
        _validate_digest(sha256_digest, "sha256_digest")
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO backups (
                    transaction_id, relative_path, backup_path, sha256, restored
                ) VALUES (?, ?, ?, ?, 0)
                ON CONFLICT(transaction_id, relative_path) DO UPDATE SET
                    backup_path = excluded.backup_path,
                    sha256 = excluded.sha256
                """,
                (transaction_id, relative_path, backup_path, sha256_digest),
            )

    def mark_backup_restored(self, transaction_id: str, relative_path: str) -> None:
        with self.transaction() as connection:
            connection.execute(
                "UPDATE backups SET restored = 1 WHERE transaction_id = ? AND relative_path = ?",
                (transaction_id, relative_path),
            )

    def backups_for_transaction(self, transaction_id: str) -> list[dict[str, Any]]:
        with self._reader() as connection:
            rows = connection.execute(
                "SELECT * FROM backups WHERE transaction_id = ? ORDER BY backup_id",
                (transaction_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def actions_for_transaction(self, transaction_id: str) -> list[dict[str, Any]]:
        with self._reader() as connection:
            rows = connection.execute(
                "SELECT * FROM actions WHERE transaction_id = ? ORDER BY sequence",
                (transaction_id,),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(str(item.pop("payload_json")))
            result.append(item)
        return result


def render_declaration(declaration: DeclarationV2) -> str:
    lines = [
        f"schema_version = {declaration.schema_version}",
        f"repository_identity = {_toml_string(declaration.repository_identity)}",
        f"catalog_digest = {_toml_string(declaration.catalog_digest)}",
    ]
    for tool in sorted(declaration.tools, key=lambda item: item.tool_id):
        lines.extend(
            (
                "",
                "[[tool]]",
                f"tool_id = {_toml_string(tool.tool_id)}",
                f"version = {_toml_string(tool.version)}",
                f"provenance = {_toml_string(tool.provenance)}",
                f"install_scope = {_toml_string(_value(tool.install_scope))}",
                f"permissions = {_toml_array(sorted(_value(item) for item in tool.permissions))}",
                f"required_env = {_toml_array(sorted(tool.required_env))}",
                f"artifacts = {_toml_array(sorted(tool.artifacts))}",
            )
        )
    return "\n".join(lines) + "\n"


def write_declaration(root: str | Path, declaration: DeclarationV2) -> Path:
    identity = repository_identity(root)
    target = resolve_owned_path(
        root,
        ".toolbelt/lock.toml",
        expected_root_identity=identity,
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target = resolve_owned_path(
        root,
        ".toolbelt/lock.toml",
        expected_root_identity=identity,
    )
    atomic_write_text(target, render_declaration(declaration))
    return target


def load_declaration(root: str | Path) -> DeclarationV2 | None:
    identity = repository_identity(root)
    target = resolve_owned_path(
        root,
        ".toolbelt/lock.toml",
        expected_root_identity=identity,
    )
    if not target.exists():
        return None
    try:
        if target.stat().st_size > 1024 * 1024:
            raise ValidationError("Toolbelt declaration exceeds one MiB")
        raw = tomllib.loads(target.read_text(encoding="utf-8"))
        if set(raw) - {"schema_version", "repository_identity", "catalog_digest", "tool"}:
            raise ValidationError("Toolbelt declaration contains unknown keys")
        payload = {
            "schema_version": raw.get("schema_version"),
            "repository_identity": raw.get("repository_identity"),
            "catalog_digest": raw.get("catalog_digest"),
            "tools": raw.get("tool", []),
        }
        return DeclarationV2.model_validate(payload)
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError, PydanticValidationError) as exc:
        raise ValidationError(f"invalid Toolbelt declaration: {exc}") from exc


def atomic_write_text(path: str | Path, content: str, *, mode: int = 0o600) -> None:
    atomic_write_bytes(path, content.encode("utf-8"), mode=mode)


def atomic_write_bytes(path: str | Path, content: bytes, *, mode: int = 0o600) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.chmod(temporary, mode)
        except OSError:
            pass
        os.replace(temporary, target)
        _fsync_directory(target.parent)
    except BaseException:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | int(getattr(os, "O_DIRECTORY", 0))
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _validate_digest(value: str, name: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{name} must be a SHA-256 digest")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _value(value: object) -> str:
    return str(value.value) if isinstance(value, Enum) else str(value)


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _toml_array(values: list[str]) -> str:
    return "[" + ", ".join(_toml_string(value) for value in values) + "]"


__all__ = [
    "STATE_SCHEMA_VERSION",
    "StateStore",
    "atomic_write_bytes",
    "atomic_write_text",
    "load_declaration",
    "render_declaration",
    "write_declaration",
]

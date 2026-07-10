from __future__ import annotations

import os
import shutil
import signal
import stat
import subprocess
import threading
import time
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, BinaryIO

from toolbelt.catalog import CatalogV2
from toolbelt.errors import ApplyError, DriftError, ValidationError, VerificationError
from toolbelt.paths import repository_identity, resolve_owned_path
from toolbelt.planner import validate_plan_binding
from toolbelt.schemas import (
    ActionOperation,
    ActionStepV2,
    ActionV2,
    CapabilitySnapshot,
    CommandResultV2,
    DeclarationV2,
    DeclaredToolV2,
    PlanV2,
    TransactionState,
)
from toolbelt.state import (
    StateStore,
    atomic_write_bytes,
    load_declaration,
    write_declaration,
)


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    transaction_id: str
    state: TransactionState
    commands: tuple[CommandResultV2, ...]
    error: str | None = None
    dry_run: bool = False


class Executor:
    def __init__(
        self,
        *,
        state_store: StateStore | None = None,
        command_timeout: float = 300.0,
        max_output_bytes: int = 64 * 1024,
        lock_timeout: float = 10.0,
        fault_after: int | None = None,
        environment: dict[str, str] | None = None,
    ) -> None:
        if command_timeout <= 0 or max_output_bytes < 1024 or lock_timeout <= 0:
            raise ValueError("executor timeouts and output bounds must be positive")
        if fault_after is not None and fault_after < 1:
            raise ValueError("fault_after must be positive")
        self._provided_store = state_store
        self.command_timeout = command_timeout
        self.max_output_bytes = min(max_output_bytes, 64 * 1024)
        self.lock_timeout = lock_timeout
        self.fault_after = fault_after
        self.environment = dict(os.environ if environment is None else environment)
        self._boundaries = 0

    def apply(
        self,
        plan: PlanV2,
        root: str | Path,
        catalog: CatalogV2,
        capabilities: CapabilitySnapshot,
        *,
        allow_network: bool = False,
        allow_user_scope: bool = False,
        allow_elevation: bool = False,
        dry_run: bool = False,
        now=None,
    ) -> ExecutionResult:
        repository_root = Path(root).resolve(strict=True)
        identity = repository_identity(repository_root)
        control = resolve_owned_path(
            repository_root,
            ".toolbelt",
            expected_root_identity=identity,
        )
        control.mkdir(parents=True, exist_ok=True)
        lock_path = resolve_owned_path(
            repository_root,
            ".toolbelt/apply.lock",
            expected_root_identity=identity,
        )
        store = self._provided_store or StateStore(control / "state.sqlite3")
        commands: list[CommandResultV2] = []
        completed: list[ActionV2] = []
        transaction_id = ""
        declaration_before: bytes | None = None
        declaration_written = False
        self._boundaries = 0

        with _ApplyLock(lock_path, timeout=self.lock_timeout):
            declaration_path = resolve_owned_path(
                repository_root,
                ".toolbelt/lock.toml",
                expected_root_identity=identity,
            )
            if declaration_path.exists():
                declaration_before = declaration_path.read_bytes()
                if len(declaration_before) > 1024 * 1024:
                    raise ValidationError("Toolbelt declaration exceeds one MiB")
            transaction_id = store.begin_transaction(
                plan_id=plan.plan_id,
                repository_identity=plan.repository.identity,
            )
            try:
                store.set_transaction_state(transaction_id, TransactionState.PREFLIGHT)
                validate_plan_binding(plan, repository_root, catalog, capabilities, now=now)
                existing = self._preflight(
                    plan,
                    repository_root,
                    catalog,
                    allow_network=allow_network,
                    allow_user_scope=allow_user_scope,
                    allow_elevation=allow_elevation,
                )
                self._checkpoint()
                store.set_transaction_state(transaction_id, TransactionState.APPLYING)
                self._checkpoint()

                if not dry_run:
                    for sequence, action in enumerate(plan.actions, start=1):
                        store.record_action(
                            transaction_id,
                            action.id,
                            sequence=sequence,
                            state="started",
                            payload=action.model_dump(mode="json"),
                        )
                        mutated = False
                        for step in action.steps:
                            result = self._run_step(step, repository_root, action.required_env)
                            commands.append(result)
                            store.record_command(
                                transaction_id,
                                action.id,
                                phase="apply",
                                argv=result.argv,
                                returncode=result.returncode,
                                stdout=result.stdout,
                                stderr=result.stderr,
                                duration_seconds=result.duration_seconds,
                                timed_out=result.timed_out,
                            )
                            if result.timed_out or result.returncode != 0:
                                raise ApplyError(f"action {action.id} failed during apply")
                            mutated = True
                        if mutated:
                            completed.append(action)
                        store.record_action(
                            transaction_id,
                            action.id,
                            sequence=sequence,
                            state="mutated",
                            payload=action.model_dump(mode="json"),
                        )
                        self._checkpoint()

                store.set_transaction_state(transaction_id, TransactionState.VERIFYING)
                self._checkpoint()
                if not dry_run:
                    for sequence, action in enumerate(plan.actions, start=1):
                        for step in action.verify:
                            result = self._run_step(step, repository_root, action.required_env)
                            commands.append(result)
                            store.record_command(
                                transaction_id,
                                action.id,
                                phase="verify",
                                argv=result.argv,
                                returncode=result.returncode,
                                stdout=result.stdout,
                                stderr=result.stderr,
                                duration_seconds=result.duration_seconds,
                                timed_out=result.timed_out,
                            )
                            if result.timed_out or result.returncode != 0:
                                raise VerificationError(f"action {action.id} failed verification")
                        store.record_action(
                            transaction_id,
                            action.id,
                            sequence=sequence,
                            state="verified",
                            payload=action.model_dump(mode="json"),
                        )
                    self._checkpoint()
                    self._checkpoint()
                    self._record_declaration_backup(
                        store,
                        transaction_id,
                        repository_root,
                        declaration_before,
                    )
                    declaration = self._updated_declaration(
                        plan,
                        catalog,
                        existing,
                    )
                    write_declaration(repository_root, declaration)
                    declaration_written = True
                    self._checkpoint()
                store.set_transaction_state(transaction_id, TransactionState.SUCCEEDED)
                return ExecutionResult(
                    transaction_id,
                    TransactionState.SUCCEEDED,
                    tuple(commands),
                    dry_run=dry_run,
                )
            except Exception as exc:
                rollback_failed = self._rollback(
                    store,
                    transaction_id,
                    repository_root,
                    completed,
                    commands,
                    declaration_before=declaration_before,
                    restore_declaration=declaration_written,
                )
                state = (
                    TransactionState.ROLLBACK_FAILED
                    if rollback_failed
                    else TransactionState.ROLLED_BACK
                )
                return ExecutionResult(
                    transaction_id,
                    state,
                    tuple(commands),
                    error=_bounded_error(exc),
                    dry_run=dry_run,
                )
            except BaseException as exc:
                try:
                    store.set_transaction_state(
                        transaction_id,
                        TransactionState.INTERRUPTED,
                        error=_bounded_error(exc),
                    )
                finally:
                    raise

    def recover(self, root: str | Path, transaction_id: str) -> ExecutionResult:
        repository_root = Path(root).resolve(strict=True)
        identity = repository_identity(repository_root)
        control = resolve_owned_path(
            repository_root,
            ".toolbelt",
            expected_root_identity=identity,
        )
        store = self._provided_store or StateStore(control / "state.sqlite3")
        lock_path = resolve_owned_path(
            repository_root,
            ".toolbelt/apply.lock",
            expected_root_identity=identity,
        )
        with _ApplyLock(lock_path, timeout=self.lock_timeout):
            transaction = store.get_transaction(transaction_id)
            if transaction is None:
                raise ValidationError(f"unknown transaction: {transaction_id}")
            current = TransactionState(str(transaction["state"]))
            if current in {
                TransactionState.SUCCEEDED,
                TransactionState.ROLLED_BACK,
                TransactionState.ROLLBACK_FAILED,
            }:
                return ExecutionResult(transaction_id, current, ())
            actions = [
                ActionV2.model_validate(item["payload"])
                for item in store.actions_for_transaction(transaction_id)
                if item["state"] in {"mutated", "verified"}
            ]
            commands: list[CommandResultV2] = []
            rollback_failed = self._rollback(
                store,
                transaction_id,
                repository_root,
                actions,
                commands,
                declaration_before=self._backup_bytes(store, repository_root, transaction_id),
                restore_declaration=bool(store.backups_for_transaction(transaction_id)),
            )
            state = (
                TransactionState.ROLLBACK_FAILED
                if rollback_failed
                else TransactionState.ROLLED_BACK
            )
            store.record_recovery(transaction_id, state.value, "recovery completed")
            return ExecutionResult(transaction_id, state, tuple(commands))

    def _preflight(
        self,
        plan: PlanV2,
        root: Path,
        catalog: CatalogV2,
        *,
        allow_network: bool,
        allow_user_scope: bool,
        allow_elevation: bool,
    ) -> DeclarationV2 | None:
        tools_by_id = {tool.id: tool for tool in catalog}
        for action in plan.actions:
            tool = tools_by_id.get(action.tool_id)
            if tool is None or tool.version != action.tool_version:
                raise DriftError(f"catalog contract missing for {action.tool_id}")
            if action.install_scope.value == "user" and not allow_user_scope:
                raise ApplyError(f"action {action.id} requires user-scope approval")
            for name in action.required_env:
                if name not in self.environment:
                    raise ApplyError(f"action {action.id} requires environment variable {name}")
            for artifact in tool.artifacts:
                resolve_owned_path(root, artifact)
            for step in (*action.steps, *action.verify, *action.rollback):
                if step.requires_network and not allow_network:
                    raise ApplyError(f"action {action.id} requires network approval")
                if step.requires_elevation and not allow_elevation:
                    raise ApplyError(f"action {action.id} requires elevation approval")
                if step.cwd is not None:
                    resolve_owned_path(root, step.cwd)
            for step in (*action.steps, *action.rollback):
                self._require_executable(step.argv[0])
        existing = load_declaration(root)
        if existing is not None:
            if existing.repository_identity != plan.repository.identity:
                raise DriftError("existing declaration belongs to a different repository identity")
            current_versions = {tool.id: tool.version for tool in catalog}
            mismatched = sorted(
                tool.tool_id
                for tool in existing.tools
                if current_versions.get(tool.tool_id) != tool.version
            )
            if mismatched:
                raise DriftError(
                    "declared tool versions differ from the current catalog: "
                    + ", ".join(mismatched)
                )
            if existing.catalog_digest != catalog.digest:
                verified = {
                    action.tool_id
                    for action in plan.actions
                    if action.operation is ActionOperation.VERIFY
                }
                declared = {tool.tool_id for tool in existing.tools}
                if verified != declared:
                    raise DriftError(
                        "catalog changed since declaration; verify every declared tool first"
                    )
            declared_ids = {tool.tool_id for tool in existing.tools}
            for action in plan.actions:
                if action.operation in {ActionOperation.INSTALL, ActionOperation.ADOPT}:
                    if action.tool_id in declared_ids:
                        raise DriftError(
                            f"tool is already declared and cannot be reinstalled: {action.tool_id}"
                        )
                elif action.operation in {ActionOperation.VERIFY, ActionOperation.REMOVE}:
                    if action.tool_id not in declared_ids:
                        raise DriftError(
                            f"tool is not declared for {action.operation.value}: {action.tool_id}"
                        )
        return existing

    def _run_step(
        self,
        step: ActionStepV2,
        root: Path,
        required_env: tuple[str, ...],
    ) -> CommandResultV2:
        cwd = root if step.cwd is None else resolve_owned_path(root, step.cwd)
        timeout = min(float(step.timeout_seconds), self.command_timeout)
        flags = 0
        popen_options: dict[str, Any] = {}
        if os.name == "nt":
            flags = int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        else:
            popen_options["start_new_session"] = True
        started = time.monotonic()
        timed_out = False
        process = subprocess.Popen(
            list(step.argv),
            cwd=cwd,
            env=self.environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            creationflags=flags,
            **popen_options,
        )
        if process.stdout is None or process.stderr is None:  # pragma: no cover - Popen contract
            raise ApplyError("subprocess pipes were not created")
        stdout_buffer = bytearray()
        stderr_buffer = bytearray()
        readers = (
            threading.Thread(
                target=_drain_pipe,
                args=(process.stdout, stdout_buffer, self.max_output_bytes),
                daemon=True,
            ),
            threading.Thread(
                target=_drain_pipe,
                args=(process.stderr, stderr_buffer, self.max_output_bytes),
                daemon=True,
            ),
        )
        for reader in readers:
            reader.start()
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _terminate_process_group(process)
        for reader in readers:
            reader.join(timeout=1)
        if any(reader.is_alive() for reader in readers):
            process.stdout.close()
            process.stderr.close()
            for reader in readers:
                reader.join(timeout=1)
        duration = time.monotonic() - started
        stdout = bytes(stdout_buffer)
        stderr = bytes(stderr_buffer)
        secrets = tuple(value for name in required_env if (value := self.environment.get(name)))
        stdout_text, stdout_redacted = _decode_and_redact(stdout, secrets)
        stderr_text, stderr_redacted = _decode_and_redact(stderr, secrets)
        return CommandResultV2(
            argv=step.argv,
            returncode=process.returncode,
            stdout=stdout_text,
            stderr=stderr_text,
            duration_seconds=duration,
            timed_out=timed_out,
            redacted=stdout_redacted or stderr_redacted,
        )

    def _rollback(
        self,
        store: StateStore,
        transaction_id: str,
        root: Path,
        completed: list[ActionV2],
        commands: list[CommandResultV2],
        *,
        declaration_before: bytes | None,
        restore_declaration: bool,
    ) -> bool:
        failed = False
        try:
            self._transition_to_rollback(store, transaction_id)
        except Exception:
            failed = True
        for action in reversed(completed):
            action_failed = False
            for step in reversed(action.rollback):
                try:
                    result = self._run_step(step, root, action.required_env)
                    commands.append(result)
                    store.record_command(
                        transaction_id,
                        action.id,
                        phase="rollback",
                        argv=result.argv,
                        returncode=result.returncode,
                        stdout=result.stdout,
                        stderr=result.stderr,
                        duration_seconds=result.duration_seconds,
                        timed_out=result.timed_out,
                    )
                    action_failed = action_failed or result.timed_out or result.returncode != 0
                except Exception:
                    action_failed = True
            failed = failed or action_failed
            try:
                row = next(
                    item
                    for item in store.actions_for_transaction(transaction_id)
                    if item["action_id"] == action.id
                )
                store.record_action(
                    transaction_id,
                    action.id,
                    sequence=int(row["sequence"]),
                    state="rollback_failed" if action_failed else "rolled_back",
                    payload=action.model_dump(mode="json"),
                )
            except Exception:
                failed = True
        if restore_declaration:
            try:
                self._restore_declaration(root, declaration_before)
                store.mark_backup_restored(transaction_id, ".toolbelt/lock.toml")
            except Exception:
                failed = True
        try:
            store.set_transaction_state(
                transaction_id,
                TransactionState.ROLLBACK_FAILED if failed else TransactionState.ROLLED_BACK,
            )
        except Exception:
            failed = True
        return failed

    def _transition_to_rollback(self, store: StateStore, transaction_id: str) -> None:
        row = store.get_transaction(transaction_id)
        if row is None:
            raise ValidationError(f"unknown transaction: {transaction_id}")
        state = TransactionState(str(row["state"]))
        if state is TransactionState.ROLLING_BACK:
            return
        if state is TransactionState.PLANNED:
            store.set_transaction_state(transaction_id, TransactionState.INTERRUPTED)
            state = TransactionState.INTERRUPTED
        store.set_transaction_state(transaction_id, TransactionState.ROLLING_BACK)

    def _updated_declaration(
        self,
        plan: PlanV2,
        catalog: CatalogV2,
        existing: DeclarationV2 | None,
    ) -> DeclarationV2:
        tools = {tool.tool_id: tool for tool in (() if existing is None else existing.tools)}
        catalog_by_id = {tool.id: tool for tool in catalog}
        for action in plan.actions:
            if action.operation is ActionOperation.REMOVE:
                tools.pop(action.tool_id, None)
                continue
            tool = catalog_by_id[action.tool_id]
            tools[action.tool_id] = DeclaredToolV2(
                tool_id=tool.id,
                version=tool.version,
                provenance=tool.provenance,
                install_scope=tool.install_scope,
                permissions=tool.permissions,
                required_env=tool.required_env,
                artifacts=tool.artifacts,
            )
        return DeclarationV2(
            repository_identity=plan.repository.identity,
            catalog_digest=plan.catalog_digest,
            tools=tuple(sorted(tools.values(), key=lambda item: item.tool_id)),
        )

    def _record_declaration_backup(
        self,
        store: StateStore,
        transaction_id: str,
        root: Path,
        content: bytes | None,
    ) -> None:
        if content is None:
            store.record_backup(
                transaction_id,
                ".toolbelt/lock.toml",
                backup_path="",
                sha256_digest="0" * 64,
            )
            return
        relative = f".toolbelt/backups/{transaction_id}/lock.toml"
        backup = resolve_owned_path(root, relative)
        atomic_write_bytes(backup, content)
        store.record_backup(
            transaction_id,
            ".toolbelt/lock.toml",
            backup_path=relative,
            sha256_digest=sha256(content).hexdigest(),
        )

    def _backup_bytes(self, store: StateStore, root: Path, transaction_id: str) -> bytes | None:
        backups = store.backups_for_transaction(transaction_id)
        if not backups:
            return None
        backup = backups[-1]
        if not backup["backup_path"]:
            return None
        content = resolve_owned_path(root, str(backup["backup_path"])).read_bytes()
        if sha256(content).hexdigest() != backup["sha256"]:
            raise DriftError("declaration recovery backup digest mismatch")
        return content

    def _restore_declaration(self, root: Path, content: bytes | None) -> None:
        target = resolve_owned_path(root, ".toolbelt/lock.toml")
        if content is None:
            target.unlink(missing_ok=True)
        else:
            atomic_write_bytes(target, content)

    def _require_executable(self, executable: str) -> None:
        if shutil.which(executable, path=self.environment.get("PATH")) is None:
            raise ApplyError(f"required executable is unavailable: {executable}")

    def _checkpoint(self) -> None:
        self._boundaries += 1
        if self.fault_after == self._boundaries:
            raise ApplyError(f"injected fault after boundary {self._boundaries}")


class _ApplyLock:
    def __init__(self, path: Path, *, timeout: float) -> None:
        self.path = path
        self.timeout = timeout
        self._stream = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_RDWR | os.O_CREAT | os.O_APPEND | int(getattr(os, "O_CLOEXEC", 0))
        flags |= int(getattr(os, "O_NOFOLLOW", 0))
        try:
            descriptor = os.open(self.path, flags, 0o600)
            opened = os.fstat(descriptor)
            current = self.path.lstat()
            if (
                stat.S_ISLNK(current.st_mode)
                or opened.st_dev != current.st_dev
                or opened.st_ino != current.st_ino
            ):
                os.close(descriptor)
                raise ApplyError("apply lock path changed during open")
            self._stream = os.fdopen(descriptor, "a+b")
        except OSError as exc:
            raise ApplyError("apply lock path is unsafe or unavailable") from exc
        self._stream.seek(0, os.SEEK_END)
        if self._stream.tell() == 0:
            self._stream.write(b"0")
            self._stream.flush()
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                if os.name == "nt":
                    import msvcrt

                    self._stream.seek(0)
                    msvcrt.locking(self._stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(self._stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except OSError as exc:
                if time.monotonic() >= deadline:
                    self._stream.close()
                    raise ApplyError("another Toolbelt apply operation holds the lock") from exc
                time.sleep(0.025)

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self._stream is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                self._stream.seek(0)
                msvcrt.locking(self._stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._stream.fileno(), fcntl.LOCK_UN)
        finally:
            self._stream.close()


def _terminate_process_group(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2,
                check=False,
                shell=False,
            )
            if process.poll() is None:
                process.terminate()
        else:
            os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=0.5)
    except (OSError, subprocess.TimeoutExpired):
        try:
            if os.name == "nt":
                process.kill()
            else:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=1)
        except (OSError, subprocess.TimeoutExpired):
            pass


def _drain_pipe(stream: BinaryIO, output: bytearray, maximum: int) -> None:
    try:
        while chunk := stream.read(64 * 1024):
            remaining = maximum - len(output)
            if remaining > 0:
                output.extend(chunk[:remaining])
    except (OSError, ValueError):
        return


def _decode_and_redact(value: bytes, secrets: tuple[str, ...]) -> tuple[str, bool]:
    text = value.decode("utf-8", errors="replace")
    redacted = False
    for secret in sorted(secrets, key=len, reverse=True):
        if secret and secret in text:
            text = text.replace(secret, "[REDACTED]")
            redacted = True
    return text, redacted


def _bounded_error(error: BaseException) -> str:
    message = f"{type(error).__name__}: {error}".strip()
    return message[:4096]


__all__ = ["ExecutionResult", "Executor"]

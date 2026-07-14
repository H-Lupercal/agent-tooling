"""Bounded execution of a trusted installer without invoking a shell."""

from __future__ import annotations

import ctypes
import hashlib
import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol, cast

from install_rehearsal.models import RunResult
from install_rehearsal.redaction import redact_text

_EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
_ELEVATION_HELPERS = {"doas", "pkexec", "runas", "sudo"}
_CREATE_NEW_PROCESS_GROUP = 0x00000200
_CREATE_SUSPENDED = 0x00000004


class _Digest(Protocol):
    def update(self, value: bytes, /) -> None: ...

    def hexdigest(self) -> str: ...


@dataclass(frozen=True)
class RunLimits:
    timeout_seconds: float = 120.0
    output_bytes: int = 64 * 1024

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("timeout must be positive")
        if self.output_bytes < 0:
            raise ValueError("output byte limit cannot be negative")


@dataclass
class _OutputCapture:
    limit: int
    prefix: bytearray
    digest: _Digest
    total_bytes: int = 0

    @classmethod
    def create(cls, limit: int) -> _OutputCapture:
        return cls(limit=limit, prefix=bytearray(), digest=hashlib.sha256())

    def feed(self, chunk: bytes) -> None:
        self.digest.update(chunk)
        self.total_bytes += len(chunk)
        remaining = self.limit - len(self.prefix)
        if remaining > 0:
            self.prefix.extend(chunk[:remaining])


def _validate_argv(argv: Sequence[str]) -> tuple[str, ...]:
    if not argv:
        raise ValueError("installer argv cannot be empty")
    if any("\0" in item for item in argv):
        raise ValueError("installer argv cannot contain NUL bytes")
    executable = argv[0].replace("\\", "/").rsplit("/", maxsplit=1)[-1].lower()
    if executable.endswith(".exe"):
        executable = executable[:-4]
    if executable in _ELEVATION_HELPERS:
        raise ValueError(f"elevation helper is not allowed: {executable}")
    return tuple(argv)


def _excerpt(capture: _OutputCapture) -> tuple[str, bool]:
    text = redact_text(bytes(capture.prefix).decode("utf-8", errors="replace"))
    encoded = text.encode("utf-8")
    return (
        encoded[: capture.limit].decode("utf-8", errors="ignore"),
        capture.total_bytes > capture.limit,
    )


def _drain(stream: BinaryIO, capture: _OutputCapture) -> None:
    try:
        for chunk in iter(lambda: stream.read(64 * 1024), b""):
            capture.feed(chunk)
    finally:
        stream.close()


def _create_windows_job(
    process: subprocess.Popen[bytes],
) -> Callable[[], None]:  # pragma: no cover - executed by Windows CI
    """Assign process descendants to a kill-on-close Windows Job Object."""
    from ctypes import wintypes

    class _BasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _IoCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class _ExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BasicLimitInformation),
            ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    win_dll = ctypes.__dict__["WinDLL"]
    get_last_error = cast(Callable[[], int], ctypes.__dict__["get_last_error"])
    kernel32 = win_dll("kernel32", use_last_error=True)
    create_job = kernel32.CreateJobObjectW
    create_job.restype = wintypes.HANDLE
    create_job.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    set_information = kernel32.SetInformationJobObject
    set_information.restype = wintypes.BOOL
    set_information.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    assign_process = kernel32.AssignProcessToJobObject
    assign_process.restype = wintypes.BOOL
    assign_process.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    close_handle = kernel32.CloseHandle
    close_handle.restype = wintypes.BOOL
    close_handle.argtypes = [wintypes.HANDLE]

    job = create_job(None, None)
    if not job:
        raise OSError(get_last_error(), "CreateJobObjectW failed")
    try:
        information = _ExtendedLimitInformation()
        information.BasicLimitInformation.LimitFlags = 0x00002000
        if not set_information(job, 9, ctypes.byref(information), ctypes.sizeof(information)):
            raise OSError(get_last_error(), "SetInformationJobObject failed")
        process_handle = getattr(process, "_handle", None)
        if process_handle is None or not assign_process(job, process_handle):
            raise OSError(get_last_error(), "AssignProcessToJobObject failed")
    except (AttributeError, OSError, TypeError, ctypes.ArgumentError) as exc:
        with suppress(Exception):
            close_handle(job)
        if isinstance(exc, OSError):
            raise
        raise OSError(f"Windows Job Object setup failed: {exc}") from exc

    closed = False

    def close() -> None:
        nonlocal closed
        if not closed:
            close_handle(job)
            closed = True

    return close


def _launch(
    argv: tuple[str, ...], cwd: Path, environment: Mapping[str, str]
) -> tuple[subprocess.Popen[bytes], Callable[[], None] | None]:
    if os.name == "nt":  # pragma: no cover - executed by Windows CI
        return _launch_windows(argv, cwd, environment)
    return (
        subprocess.Popen(
            argv,
            cwd=cwd,
            env=dict(environment),
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        ),
        None,
    )


def _launch_windows(
    argv: tuple[str, ...], cwd: Path, environment: Mapping[str, str]
) -> tuple[subprocess.Popen[bytes], Callable[[], None]]:  # pragma: no cover - Windows only
    process = subprocess.Popen(
        argv,
        cwd=cwd,
        env=dict(environment),
        shell=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=_CREATE_NEW_PROCESS_GROUP | _CREATE_SUSPENDED,
    )
    close_job: Callable[[], None] | None = None
    try:
        close_job = _create_windows_job(process)
        _resume_windows_process(process)
        return process, close_job
    except (AttributeError, KeyError, OSError, TypeError, ctypes.ArgumentError) as exc:
        if close_job is not None:
            try:
                close_job()
            except (OSError, TypeError, ctypes.ArgumentError):
                with suppress(OSError):
                    process.kill()
        else:
            with suppress(OSError):
                process.kill()
        with suppress(subprocess.TimeoutExpired):
            process.wait(timeout=1)
        if isinstance(exc, OSError):
            raise
        raise OSError(f"Windows process containment failed: {exc}") from exc


def _resume_windows_process(
    process: subprocess.Popen[bytes],
) -> None:  # pragma: no cover - executed by Windows CI
    from ctypes import wintypes

    win_dll = ctypes.__dict__["WinDLL"]
    ntdll = win_dll("ntdll")
    resume_process = ntdll.NtResumeProcess
    resume_process.restype = ctypes.c_long
    resume_process.argtypes = [wintypes.HANDLE]
    process_handle = getattr(process, "_handle", None)
    if process_handle is None:
        raise OSError("suspended Windows process has no native handle")
    status = int(resume_process(process_handle))
    if status != 0:
        raise OSError(status, "NtResumeProcess failed")


def _stop_process_tree(
    process: subprocess.Popen[bytes], close_windows_job: Callable[[], None] | None
) -> None:
    if close_windows_job is not None:  # pragma: no cover - executed by Windows CI
        close_windows_job()
        with suppress(subprocess.TimeoutExpired):
            process.wait(timeout=1)
        return
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    with suppress(subprocess.TimeoutExpired):
        process.wait(timeout=1)
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.01)
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)


def _start_capture_threads(
    process: subprocess.Popen[bytes], limit: int
) -> tuple[_OutputCapture, _OutputCapture, tuple[threading.Thread, threading.Thread]]:
    if process.stdout is None or process.stderr is None:
        raise RuntimeError("process output pipes were not created")
    stdout = _OutputCapture.create(limit)
    stderr = _OutputCapture.create(limit)
    threads = (
        threading.Thread(target=_drain, args=(process.stdout, stdout), daemon=True),
        threading.Thread(target=_drain, args=(process.stderr, stderr), daemon=True),
    )
    for thread in threads:
        thread.start()
    return stdout, stderr, threads


def _join_capture_threads(threads: tuple[threading.Thread, threading.Thread]) -> None:
    for thread in threads:
        thread.join(timeout=2)
        if thread.is_alive():
            raise RuntimeError("output capture did not quiesce after process-tree termination")


def run_command(
    argv: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    limits: RunLimits,
) -> RunResult:
    """Execute argv directly and return deterministic bounded evidence."""
    validated_argv = _validate_argv(argv)
    started = time.monotonic()
    try:
        process, close_windows_job = _launch(validated_argv, cwd, environment)
    except OSError as exc:
        duration = time.monotonic() - started
        stderr_bytes = redact_text(str(exc)).encode("utf-8")
        stderr = _OutputCapture.create(limits.output_bytes)
        stderr.feed(stderr_bytes)
        excerpt, truncated = _excerpt(stderr)
        return RunResult(
            exit_code=None,
            termination_reason="launch_error",
            duration_seconds=duration,
            stdout_sha256=_EMPTY_SHA256,
            stderr_sha256=stderr.digest.hexdigest(),
            stdout_excerpt="",
            stderr_excerpt=excerpt,
            stdout_truncated=False,
            stderr_truncated=truncated,
        )

    stdout, stderr, capture_threads = _start_capture_threads(process, limits.output_bytes)
    try:
        process.wait(timeout=limits.timeout_seconds)
        termination_reason = "exited"
        exit_code = process.returncode
    except subprocess.TimeoutExpired:
        termination_reason = "timeout"
        exit_code = None
    finally:
        _stop_process_tree(process, close_windows_job)
        with suppress(subprocess.TimeoutExpired):
            process.wait(timeout=1)
        _join_capture_threads(capture_threads)

    stdout_excerpt, stdout_truncated = _excerpt(stdout)
    stderr_excerpt, stderr_truncated = _excerpt(stderr)
    return RunResult(
        exit_code=exit_code,
        termination_reason=termination_reason,  # type: ignore[arg-type]
        duration_seconds=time.monotonic() - started,
        stdout_sha256=stdout.digest.hexdigest(),
        stderr_sha256=stderr.digest.hexdigest(),
        stdout_excerpt=stdout_excerpt,
        stderr_excerpt=stderr_excerpt,
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
    )

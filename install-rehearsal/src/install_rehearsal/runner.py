"""Bounded execution of a trusted installer without invoking a shell."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import signal
import subprocess
import time
from typing import Mapping, Sequence

from install_rehearsal.models import RunResult
from install_rehearsal.redaction import redact_text

_EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
_ELEVATION_HELPERS = {"doas", "pkexec", "runas", "sudo"}


@dataclass(frozen=True)
class RunLimits:
    timeout_seconds: float = 120.0
    output_bytes: int = 64 * 1024

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("timeout must be positive")
        if self.output_bytes < 0:
            raise ValueError("output byte limit cannot be negative")


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


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    if os.name == "nt":
        process.terminate()
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            process.kill()
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def _excerpt(data: bytes, limit: int) -> tuple[str, bool]:
    text = redact_text(data.decode("utf-8", errors="replace"))
    encoded = text.encode("utf-8")
    return encoded[:limit].decode("utf-8", errors="ignore"), len(data) > limit


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
    popen_kwargs: dict[str, object] = {}
    if os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["start_new_session"] = True

    try:
        process = subprocess.Popen(  # noqa: S603 - argv is the feature's explicit trusted input
            validated_argv,
            cwd=cwd,
            env=dict(environment),
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **popen_kwargs,
        )
    except OSError as exc:
        duration = time.monotonic() - started
        stderr = redact_text(str(exc)).encode("utf-8")
        excerpt, truncated = _excerpt(stderr, limits.output_bytes)
        return RunResult(
            exit_code=None,
            termination_reason="launch_error",
            duration_seconds=duration,
            stdout_sha256=_EMPTY_SHA256,
            stderr_sha256=hashlib.sha256(stderr).hexdigest(),
            stdout_excerpt="",
            stderr_excerpt=excerpt,
            stdout_truncated=False,
            stderr_truncated=truncated,
        )

    termination_reason = "exited"
    exit_code: int | None
    try:
        stdout, stderr = process.communicate(timeout=limits.timeout_seconds)
        exit_code = process.returncode
    except subprocess.TimeoutExpired:
        termination_reason = "timeout"
        _terminate_process_tree(process)
        stdout, stderr = process.communicate()
        exit_code = None

    stdout_excerpt, stdout_truncated = _excerpt(stdout, limits.output_bytes)
    stderr_excerpt, stderr_truncated = _excerpt(stderr, limits.output_bytes)
    return RunResult(
        exit_code=exit_code,
        termination_reason=termination_reason,  # type: ignore[arg-type]
        duration_seconds=time.monotonic() - started,
        stdout_sha256=hashlib.sha256(stdout).hexdigest(),
        stderr_sha256=hashlib.sha256(stderr).hexdigest(),
        stdout_excerpt=stdout_excerpt,
        stderr_excerpt=stderr_excerpt,
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
    )


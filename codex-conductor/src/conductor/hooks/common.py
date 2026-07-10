from __future__ import annotations

import datetime as _dt
import json
import os
import re
import stat
import sys

from conductor.config import conductor_home

_SECRET_PATTERNS = (
    re.compile(
        r"(?i)\b(api[_-]?key|token|secret|password|authorization)\b\s*[:=]\s*[^\s,;]+"
    ),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"\b(?:sk|pk)-[A-Za-z0-9_-]{8,}\b"),
)
MAX_HOOK_PAYLOAD_BYTES = 1_048_576


def read_payload() -> dict:
    raw = sys.stdin.read(MAX_HOOK_PAYLOAD_BYTES + 1)
    if (
        len(raw) > MAX_HOOK_PAYLOAD_BYTES
        or len(raw.encode("utf-8")) > MAX_HOOK_PAYLOAD_BYTES
    ):
        raise ValueError(f"hook payload exceeds {MAX_HOOK_PAYLOAD_BYTES} byte limit")
    if not raw.strip():
        return {}
    value = json.loads(raw)
    return value if isinstance(value, dict) else {}


def write_json(value: dict) -> None:
    sys.stdout.write(json.dumps(value) + "\n")


def log_error(hook_name: str, exc: BaseException) -> None:
    try:
        state = conductor_home() / "state"
        state.mkdir(parents=True, exist_ok=True)
        if state.is_symlink():
            return
        stamp = _dt.datetime.now(_dt.UTC).isoformat()
        path = state / "errors.log"
        if path.is_symlink():
            return
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags, 0o600)
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                return
            message = _redacted_error(exc)
            record = f"{stamp}\t{hook_name[:64]}\t{type(exc).__name__}: {message}\n"
            os.write(descriptor, record.encode("utf-8", errors="replace"))
        finally:
            os.close(descriptor)
    except OSError:
        pass


def _redacted_error(exc: BaseException) -> str:
    message = str(exc).replace("\r", " ").replace("\n", " ")[:2048]
    for pattern in _SECRET_PATTERNS:
        message = pattern.sub("<redacted>", message)
    return message

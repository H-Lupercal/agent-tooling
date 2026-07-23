from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from conductor.pricing import TokenUsage, token_usage_from_dict

MAX_SESSION_METADATA_BYTES = 65_536


@dataclass(frozen=True)
class SessionMeta:
    thread_id: str
    parent_thread_id: str | None
    thread_source: str | None
    model_provider: str | None
    cwd: str


def read_session_meta(path: Path) -> SessionMeta:
    first = _read_first_line(Path(path), max_bytes=MAX_SESSION_METADATA_BYTES)
    if first is None:
        raise ValueError("session metadata is unavailable or oversized")
    try:
        event = json.loads(first.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid session metadata: {exc}") from exc
    if not isinstance(event, dict) or not isinstance(event.get("payload"), dict):
        raise ValueError("invalid session metadata: payload must be an object")
    payload = event["payload"]
    return SessionMeta(
        thread_id=str(payload.get("id") or payload.get("thread_id") or ""),
        parent_thread_id=payload.get("parent_thread_id"),
        thread_source=payload.get("thread_source"),
        model_provider=payload.get("model_provider"),
        cwd=str(payload.get("cwd") or ""),
    )


def latest_usage(path: Path) -> TokenUsage | None:
    data = _read_file(Path(path), max_bytes=64 * 1024 * 1024, tail_bytes=262_144)
    if data is None:
        return None
    lines = data.decode("utf-8", errors="replace").splitlines()
    for line in reversed(lines):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "token_count":
            usage = token_usage_from_dict(
                event.get("payload", {}).get("total_token_usage")
            )
            if usage is not None:
                return usage
    return None


def latest_reasoning_effort(path: Path) -> str | None:
    data = _read_file(Path(path), max_bytes=64 * 1024 * 1024, tail_bytes=262_144)
    if data is None:
        return None
    for line in reversed(data.decode("utf-8", errors="replace").splitlines()):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "turn_context":
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        effort = payload.get("effort")
        if not isinstance(effort, str) or not effort:
            collaboration_mode = payload.get("collaboration_mode")
            settings = (
                collaboration_mode.get("settings")
                if isinstance(collaboration_mode, dict)
                else None
            )
            effort = (
                settings.get("reasoning_effort") if isinstance(settings, dict) else None
            )
        if isinstance(effort, str) and 0 < len(effort) <= 64:
            return effort
    return None


def claude_transcript_usage(path: Path) -> tuple[str, dict[str, int]] | None:
    """Aggregate one bounded child transcript without using parent sidechains."""

    data = _read_file(Path(path), max_bytes=8 * 1024 * 1024)
    if data is None:
        return None
    totals = {
        "input_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "output_tokens": 0,
    }
    models: set[str] = set()
    found = False
    for line in data.decode("utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "assistant":
            continue
        message = event.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("usage"), dict):
            continue
        model = message.get("model")
        if isinstance(model, str) and model:
            models.add(model)
        usage = message["usage"]
        try:
            for key in totals:
                value = usage.get(key, 0)
                if isinstance(value, bool) or int(value) < 0:
                    return None
                totals[key] += int(value)
        except (TypeError, ValueError):
            return None
        found = True
    if not found or len(models) != 1:
        return None
    return next(iter(models)), totals


def _read_file(
    path: Path,
    *,
    max_bytes: int,
    tail_bytes: int | None = None,
) -> bytes | None:
    path = Path(path)
    descriptor: int | None = None
    try:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        elif path.is_symlink():
            return None
        descriptor = os.open(path, flags)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > max_bytes:
            return None
        read_size = metadata.st_size
        if tail_bytes is not None:
            read_size = min(read_size, tail_bytes)
            os.lseek(descriptor, metadata.st_size - read_size, os.SEEK_SET)
        return os.read(descriptor, read_size)
    except OSError:
        return None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _read_first_line(path: Path, *, max_bytes: int) -> bytes | None:
    descriptor: int | None = None
    try:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        elif path.is_symlink():
            return None
        descriptor = os.open(path, flags)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            return None
        data = bytearray()
        while len(data) <= max_bytes:
            chunk = os.read(descriptor, min(8192, max_bytes + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
            newline = data.find(b"\n")
            if newline >= 0:
                return bytes(data[:newline])
        return bytes(data) if len(data) <= max_bytes else None
    except OSError:
        return None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def find_rollout(thread_id: str, sessions_root: Path) -> Path | None:
    if not thread_id:
        return None
    root = Path(sessions_root)
    if not root.exists():
        return None
    suffix = f"{thread_id}.jsonl"
    matches = sorted(
        root.glob(f"**/rollout-*{suffix}"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if matches:
        return matches[0]
    for candidate in sorted(
        root.glob("**/rollout-*.jsonl"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    ):
        try:
            if read_session_meta(candidate).thread_id == thread_id:
                return candidate
        except (OSError, ValueError):
            continue
    return None

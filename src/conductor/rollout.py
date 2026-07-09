from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from conductor.pricing import TokenUsage, token_usage_from_dict


@dataclass(frozen=True)
class SessionMeta:
    thread_id: str
    parent_thread_id: str | None
    thread_source: str | None
    model_provider: str | None
    cwd: str


def read_session_meta(path: Path) -> SessionMeta:
    with Path(path).open("r", encoding="utf-8") as handle:
        first = handle.readline()
    event = json.loads(first)
    payload = event.get("payload", {})
    return SessionMeta(
        thread_id=str(payload.get("id") or payload.get("thread_id") or ""),
        parent_thread_id=payload.get("parent_thread_id"),
        thread_source=payload.get("thread_source"),
        model_provider=payload.get("model_provider"),
        cwd=str(payload.get("cwd") or ""),
    )


def latest_usage(path: Path) -> TokenUsage | None:
    path = Path(path)
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            handle.seek(max(0, size - 262_144))
            lines = handle.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "token_count":
            usage = token_usage_from_dict(event.get("payload", {}).get("total_token_usage"))
            if usage is not None:
                return usage
    return None


def find_rollout(thread_id: str, sessions_root: Path) -> Path | None:
    if not thread_id:
        return None
    root = Path(sessions_root)
    if not root.exists():
        return None
    suffix = f"{thread_id}.jsonl"
    matches = sorted(root.glob(f"**/rollout-*{suffix}"), key=lambda path: path.stat().st_mtime, reverse=True)
    if matches:
        return matches[0]
    for candidate in sorted(root.glob("**/rollout-*.jsonl"), key=lambda path: path.stat().st_mtime, reverse=True):
        try:
            if read_session_meta(candidate).thread_id == thread_id:
                return candidate
        except (OSError, json.JSONDecodeError):
            continue
    return None

from __future__ import annotations

import fcntl
import json
import time
from collections import defaultdict
from pathlib import Path

from conductor.config import conductor_home


def run_state_dir(run_id: str) -> Path:
    return conductor_home() / "state" / run_id


def append_event(run_id: str, event: dict) -> None:
    state = run_state_dir(run_id)
    state.mkdir(parents=True, exist_ok=True)
    lock_path = state / ".ledger.lock"
    record = {"v": 1, "ts": time.time(), **event}
    with lock_path.open("a", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            with (state / "ledger.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True) + "\n")
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def read_events(run_id: str) -> list[dict]:
    path = run_state_dir(run_id) / "ledger.jsonl"
    events: list[dict] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return events
    for line in lines:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            events.append(value)
    return events


def active_spawns(events: list[dict]) -> dict[str, list[dict]]:
    active: dict[str, dict[str, dict]] = defaultdict(dict)
    for event in events:
        name = event.get("event")
        tier = str(event.get("tier") or "unknown")
        thread_id = event.get("thread_id") or event.get("task_name")
        if name == "subagent_start":
            active[tier][str(thread_id)] = event
        elif name == "subagent_stop" and thread_id is not None:
            for bucket in active.values():
                bucket.pop(str(thread_id), None)
    return {tier: list(items.values()) for tier, items in active.items()}


def spent_usd(events: list[dict]) -> float:
    return sum(float(event.get("usd") or 0.0) for event in events if event.get("event") == "cost_recorded")


def same_tier_root_spawns(events: list[dict]) -> int:
    return sum(
        1
        for event in events
        if event.get("event") == "spawn_approved"
        and event.get("caller_depth") == 0
        and event.get("caller_tier") == event.get("tier")
    )


def latest_run_id() -> str | None:
    state = conductor_home() / "state"
    if not state.exists():
        return None
    dirs = [path for path in state.iterdir() if path.is_dir()]
    if not dirs:
        return None
    return max(dirs, key=lambda path: path.stat().st_mtime).name


def reserved_usd(events: list[dict], tiers_by_name: dict[str, object]) -> float:
    total = 0.0
    for tier, open_events in active_spawns(events).items():
        tier_obj = tiers_by_name.get(tier)
        est = float(getattr(tier_obj, "est_task_usd", 0.0))
        total += est * len(open_events)
    return total

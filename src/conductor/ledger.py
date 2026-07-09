from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from conductor.config import conductor_home
from conductor.store import Store


_STORES: dict[Path, Store] = {}


def store_path() -> Path:
    return conductor_home() / "state" / "conductor.db"


def _store() -> Store:
    path = store_path()
    store = _STORES.get(path)
    if store is None:
        store = Store(path)
        _STORES[path] = store
    return store


def run_state_dir(run_id: str) -> Path:
    from conductor.store import validate_identifier

    validate_identifier(run_id, "run_id")
    return conductor_home() / "state" / run_id


def append_event(run_id: str, event: dict) -> None:
    run_state_dir(run_id).mkdir(parents=True, exist_ok=True)
    _store().append_legacy_event(run_id, event)


def read_events(run_id: str) -> list[dict]:
    if not store_path().exists():
        return []
    return _store().read_legacy_events(run_id)


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
    return sum(
        float(event.get("usd") or 0.0)
        for event in events
        if event.get("event") == "cost_recorded"
    )


def same_tier_root_spawns(events: list[dict]) -> int:
    return sum(
        1
        for event in events
        if event.get("event") == "spawn_approved"
        and event.get("caller_depth") == 0
        and event.get("caller_tier") == event.get("tier")
    )


def latest_run_id() -> str | None:
    path = store_path()
    if path.exists():
        latest = _store().latest_run_id()
        if latest is not None:
            return latest
    state = conductor_home() / "state"
    if not state.exists():
        return None
    directories = [candidate for candidate in state.iterdir() if candidate.is_dir()]
    if not directories:
        return None
    return max(directories, key=lambda candidate: candidate.stat().st_mtime).name


def reserved_usd(events: list[dict], tiers_by_name: dict[str, object]) -> float:
    total = 0.0
    for tier, open_events in active_spawns(events).items():
        tier_obj = tiers_by_name.get(tier)
        estimate = float(getattr(tier_obj, "est_task_usd", 0.0))
        total += estimate * len(open_events)
    return total

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from agent_harness.models import Event
from agent_harness.store import EventStore


def test_append_assigns_monotonic_sequences(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events.db")

    first = store.append(Event.example("run-1"))
    second = store.append(Event.example("run-1"))

    assert (first.sequence, second.sequence) == (1, 2)
    assert store.replay("run-1") == [first, second]


def test_concurrent_appends_do_not_duplicate_sequences(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events.db")

    with ThreadPoolExecutor(max_workers=4) as pool:
        events = list(pool.map(lambda _: store.append(Event.example("run-1")), range(20)))

    assert sorted(event.sequence for event in events) == list(range(1, 21))
    assert [event.sequence for event in store.replay("run-1")] == list(range(1, 21))

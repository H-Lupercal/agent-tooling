import asyncio
from pathlib import Path

import pytest

from agent_harness.models import Event
from agent_harness.room import CollaborationRoom
from agent_harness.store import EventStore


def test_publish_persists_before_fan_out(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = EventStore(tmp_path / "events.db")
        room = CollaborationRoom(store, queue_size=2)
        first = room.subscribe("agent-a")
        second = room.subscribe("agent-b")

        persisted = await room.publish(Event.example("run-1"))

        assert store.replay("run-1") == [persisted]
        assert (await first.get()).sequence == persisted.sequence
        assert (await second.get()).sequence == persisted.sequence

    asyncio.run(scenario())


def test_slow_consumer_applies_backpressure(tmp_path: Path) -> None:
    async def scenario() -> None:
        room = CollaborationRoom(EventStore(tmp_path / "events.db"), queue_size=1)
        queue = room.subscribe("slow")
        await room.publish(Event.example("run-1"))

        blocked = asyncio.create_task(room.publish(Event.example("run-1")))
        await asyncio.sleep(0.05)
        assert not blocked.done()

        await queue.get()
        persisted = await blocked
        assert persisted.sequence == 2

    asyncio.run(scenario())


def test_room_rejects_invalid_queue_and_duplicate_subscriber(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events.db")
    with pytest.raises(ValueError, match="queue size"):
        CollaborationRoom(store, queue_size=0)

    room = CollaborationRoom(store)
    room.subscribe("same")
    with pytest.raises(ValueError, match="duplicate subscriber"):
        room.subscribe("same")

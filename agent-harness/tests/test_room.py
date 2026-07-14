import asyncio
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import cast

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


def test_subscriber_cannot_mutate_shared_event_payload(tmp_path: Path) -> None:
    async def scenario() -> None:
        room = CollaborationRoom(EventStore(tmp_path / "immutable.db"))
        first = room.subscribe("first")
        second = room.subscribe("second")
        event = replace(
            Event.example("run-immutable"),
            payload={"status": "original", "items": ["one"]},
        )

        await room.publish(event)
        first_event = await first.get()
        with pytest.raises(TypeError):
            cast(dict[str, object], first_event.payload)["status"] = "changed"
        with pytest.raises(AttributeError):
            cast(list[object], first_event.payload["items"]).append("two")

        second_event = await second.get()
        assert second_event.payload == {"status": "original", "items": ("one",)}

    asyncio.run(scenario())


def test_slow_persistence_does_not_block_event_loop(tmp_path: Path) -> None:
    class SlowStore(EventStore):
        def append(self, event: Event) -> Event:
            time.sleep(0.1)
            return super().append(event)

    async def scenario() -> None:
        room = CollaborationRoom(SlowStore(tmp_path / "slow.db"))
        publish = asyncio.create_task(room.publish(Event.example("run-slow")))

        await asyncio.sleep(0.01)
        assert not publish.done()
        assert (await publish).sequence == 1

    asyncio.run(scenario())


def test_concurrent_publish_delivers_persisted_sequence_order(tmp_path: Path) -> None:
    class ReorderingStore(EventStore):
        def __init__(self, path: Path) -> None:
            super().__init__(path)
            self._next = 0
            self._counter_lock = threading.Lock()
            self.first_entered = threading.Event()

        def append(self, event: Event) -> Event:
            with self._counter_lock:
                self._next += 1
                sequence = self._next
            if sequence == 1:
                self.first_entered.set()
                time.sleep(0.05)
            return replace(event, sequence=sequence)

    async def scenario() -> None:
        store = ReorderingStore(tmp_path / "reordered.db")
        room = CollaborationRoom(store)
        subscriber = room.subscribe("observer")
        first = asyncio.create_task(room.publish(Event.example("run-order")))
        while not store.first_entered.is_set():
            await asyncio.sleep(0)
        second = asyncio.create_task(room.publish(Event.example("run-order")))
        await asyncio.gather(first, second)

        delivered = [(await subscriber.get()).sequence for _ in range(2)]
        assert delivered == [1, 2]

    asyncio.run(scenario())

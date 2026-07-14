"""Asynchronous, persist-before-publish collaboration room."""

from __future__ import annotations

import asyncio

from agent_harness.models import Event
from agent_harness.store import EventStore


class CollaborationRoom:
    def __init__(self, store: EventStore, queue_size: int = 100) -> None:
        if queue_size < 1:
            raise ValueError("queue size must be positive")
        self.store = store
        self.queue_size = queue_size
        self._subscribers: dict[str, asyncio.Queue[Event]] = {}
        self._publish_lock = asyncio.Lock()

    def subscribe(self, participant_id: str) -> asyncio.Queue[Event]:
        if participant_id in self._subscribers:
            raise ValueError(f"duplicate subscriber: {participant_id}")
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=self.queue_size)
        self._subscribers[participant_id] = queue
        return queue

    async def publish(self, event: Event) -> Event:
        async with self._publish_lock:
            persisted = await asyncio.to_thread(self.store.append, event)
            for participant_id in sorted(self._subscribers):
                await self._subscribers[participant_id].put(persisted)
            return persisted

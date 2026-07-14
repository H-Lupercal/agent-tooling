"""Run lifecycle and concurrent participant orchestration."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime

from agent_harness.adapters.base import ParticipantAdapter
from agent_harness.models import Event
from agent_harness.room import CollaborationRoom


class RunController:
    def __init__(
        self,
        *,
        run_id: str,
        adapters: Mapping[str, ParticipantAdapter],
        room: CollaborationRoom,
        max_simultaneous_speakers: int,
    ) -> None:
        if max_simultaneous_speakers < 1:
            raise ValueError("simultaneous speaker limit must be positive")
        if any(key != adapter.participant.participant_id for key, adapter in adapters.items()):
            raise ValueError("adapter keys must match participant IDs")
        self.run_id = run_id
        self.adapters = dict(adapters)
        self.room = room
        self._speaker_slots = asyncio.Semaphore(max_simultaneous_speakers)
        self._responding_count = 0

    @property
    def responding_count(self) -> int:
        return self._responding_count

    async def _publish(self, kind: str, actor: str, payload: dict[str, object]) -> Event:
        return await self.room.publish(
            Event(
                schema_version=1,
                run_id=self.run_id,
                sequence=1,
                occurred_at=datetime.now(UTC),
                actor=actor,
                kind=kind,
                causation_id=None,
                correlation_id=self.run_id,
                payload=payload,
            )
        )

    async def _respond(self, participant_id: str, prompt: str) -> None:
        adapter = self.adapters[participant_id]
        counted = False
        async with self._speaker_slots:
            try:
                async for emission in adapter.respond(prompt):
                    if not counted:
                        self._responding_count += 1
                        counted = True
                    await self._publish(
                        emission.kind,
                        participant_id,
                        {"content": emission.content},
                    )
            finally:
                if counted:
                    self._responding_count -= 1

    async def run(self, goal: str) -> None:
        await self._publish("run.started", "user", {"goal": goal})
        for participant_id in sorted(self.adapters):
            participant = self.adapters[participant_id].participant
            await self._publish(
                "participant.joined",
                "runtime",
                {
                    "participant_id": participant_id,
                    "adapter": participant.adapter,
                    "model": participant.model,
                    "roles": list(participant.roles),
                    "parent_id": participant.parent_id,
                },
            )
        await asyncio.gather(
            *(self._respond(participant_id, goal) for participant_id in sorted(self.adapters))
        )
        await self._publish("run.completed", "runtime", {})

    async def wait_until_responding(self, count: int, timeout: float = 2.0) -> None:
        async with asyncio.timeout(timeout):
            while self._responding_count < count:
                await asyncio.sleep(0)

    async def interrupt(
        self,
        participant_id: str,
        *,
        priority: str,
        reason: str,
        evidence: str | None,
    ) -> bool:
        if priority == "urgent" and not evidence:
            raise ValueError("urgent interruption requires evidence")
        if participant_id not in self.adapters:
            raise ValueError(f"unknown participant: {participant_id}")
        await self._publish(
            "interrupt.requested",
            "user",
            {
                "target": participant_id,
                "priority": priority,
                "reason": reason,
                "evidence": evidence,
            },
        )
        hard = await self.adapters[participant_id].interrupt(reason)
        await self._publish(
            "interrupt.applied",
            "runtime",
            {"target": participant_id, "mode": "hard" if hard else "queued"},
        )
        return hard

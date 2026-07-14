"""Run lifecycle and concurrent participant orchestration."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from agent_harness.adapters.base import ParticipantAdapter
from agent_harness.models import CapacityPolicy, ChildRequest, Event, Participant
from agent_harness.room import CollaborationRoom


class RunController:
    def __init__(
        self,
        *,
        run_id: str,
        adapters: Mapping[str, ParticipantAdapter],
        room: CollaborationRoom,
        max_simultaneous_speakers: int,
        capacity: CapacityPolicy | None = None,
        total_token_budget: int = 1,
        child_adapter_factory: (
            Callable[[Participant, ChildRequest], ParticipantAdapter] | None
        ) = None,
    ) -> None:
        if max_simultaneous_speakers < 1:
            raise ValueError("simultaneous speaker limit must be positive")
        if any(key != adapter.participant.participant_id for key, adapter in adapters.items()):
            raise ValueError("adapter keys must match participant IDs")
        self.run_id = run_id
        self.adapters = dict(adapters)
        self.room = room
        self.capacity = capacity or CapacityPolicy(
            max_participants=max(1, len(adapters)),
            max_dynamic_children=0,
            max_children_per_parent=0,
            max_spawn_depth=0,
            max_simultaneous_speakers=max_simultaneous_speakers,
        )
        if len(adapters) > self.capacity.max_participants:
            raise ValueError("configured root roster exceeds participant capacity")
        if total_token_budget <= 0:
            raise ValueError("total token budget must be positive")
        self._remaining_token_budget = total_token_budget
        self._child_adapter_factory = child_adapter_factory
        self._dynamic_children = 0
        self._children_per_parent: dict[str, int] = {}
        self._contexts: dict[str, tuple[str, ...]] = {
            participant_id: () for participant_id in adapters
        }
        self._speaker_slots = asyncio.Semaphore(max_simultaneous_speakers)
        self._control_operation = asyncio.Lock()
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
        async with self._control_operation:
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
        async with self._control_operation:
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

    def context_for(self, participant_id: str) -> tuple[str, ...]:
        try:
            return self._contexts[participant_id]
        except KeyError as exc:
            raise ValueError(f"unknown participant: {participant_id}") from exc

    def _spawn_depth(self, participant_id: str) -> int:
        depth = 0
        current = self.adapters[participant_id].participant
        while current.parent_id is not None:
            depth += 1
            current = self.adapters[current.parent_id].participant
        return depth

    async def _reject_spawn(self, parent_id: str, role: str, reason: str) -> None:
        await self._publish(
            "participant.spawn_rejected",
            "runtime",
            {"parent_id": parent_id, "role": role, "reason": reason},
        )
        raise RuntimeError(reason)

    async def spawn_child(
        self,
        parent_id: str,
        role: str,
        objective: str,
        context: tuple[str, ...],
        token_budget: int,
    ) -> Participant:
        request = ChildRequest(role, objective, context, token_budget)
        await self._publish(
            "participant.spawn_requested",
            parent_id,
            {
                "parent_id": parent_id,
                "role": role,
                "objective": objective,
                "token_budget": token_budget,
            },
        )
        if parent_id not in self.adapters:
            await self._reject_spawn(parent_id, role, "unknown parent participant")
        if len(self.adapters) >= self.capacity.max_participants:
            await self._reject_spawn(parent_id, role, "participant capacity exceeded")
        if self._dynamic_children >= self.capacity.max_dynamic_children:
            await self._reject_spawn(parent_id, role, "dynamic child capacity exceeded")
        child_count = self._children_per_parent.get(parent_id, 0)
        if child_count >= self.capacity.max_children_per_parent:
            await self._reject_spawn(parent_id, role, "children-per-parent capacity exceeded")
        if self._spawn_depth(parent_id) + 1 > self.capacity.max_spawn_depth:
            await self._reject_spawn(parent_id, role, "spawn depth exceeded")
        if request.token_budget > self._remaining_token_budget:
            await self._reject_spawn(parent_id, role, "token budget exceeded")
        if self._child_adapter_factory is None:
            await self._reject_spawn(parent_id, role, "child adapter factory is unavailable")

        ordinal = child_count + 1
        parent = self.adapters[parent_id].participant
        child = Participant(
            participant_id=f"{parent_id}/{role}-{ordinal}",
            adapter=parent.adapter,
            model=parent.model,
            roles=(role,),
            context_limit=parent.context_limit,
            parent_id=parent_id,
        )
        factory = self._child_adapter_factory
        if factory is None:
            raise AssertionError("child adapter factory disappeared after validation")
        adapter = factory(child, request)
        self.adapters[child.participant_id] = adapter
        self._contexts[child.participant_id] = tuple(context)
        self._children_per_parent[parent_id] = ordinal
        self._dynamic_children += 1
        self._remaining_token_budget -= request.token_budget
        await self._publish(
            "participant.admitted",
            "runtime",
            {
                "participant_id": child.participant_id,
                "parent_id": parent_id,
                "role": role,
                "token_budget": token_budget,
            },
        )
        return child

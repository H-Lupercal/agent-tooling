import asyncio
from pathlib import Path

import pytest

from agent_harness.adapters.fake import FakeAdapter
from agent_harness.controller import RunController
from agent_harness.models import CapacityPolicy, ChildRequest, Participant
from agent_harness.room import CollaborationRoom
from agent_harness.store import EventStore


def _participant(participant_id: str) -> Participant:
    return Participant(participant_id, "fake", "fake-v1", ("implementation",), 4096, None)


def _controller(
    tmp_path: Path,
    gates: list[asyncio.Event],
    *,
    max_speakers: int,
) -> RunController:
    adapters = {
        f"agent-{index}": FakeAdapter(
            _participant(f"agent-{index}"),
            scripts=((f"response-{index}",),),
            pause=gate,
        )
        for index, gate in enumerate(gates, start=1)
    }
    store = EventStore(tmp_path / "events.db")
    return RunController(
        run_id="run-1",
        adapters=adapters,
        room=CollaborationRoom(store),
        max_simultaneous_speakers=max_speakers,
    )


def test_controller_allows_configured_concurrent_speakers(tmp_path: Path) -> None:
    async def scenario() -> None:
        gates = [asyncio.Event(), asyncio.Event()]
        controller = _controller(tmp_path, gates, max_speakers=2)

        run = asyncio.create_task(controller.run("compare implementations"))
        await controller.wait_until_responding(2)
        assert controller.responding_count == 2

        for gate in gates:
            gate.set()
        await run
        assert controller.responding_count == 0
        assert controller.room.store.replay("run-1")[-1].kind == "run.completed"

    asyncio.run(scenario())


def test_urgent_interrupt_requires_reason_and_evidence(tmp_path: Path) -> None:
    async def scenario() -> None:
        gate = asyncio.Event()
        controller = _controller(tmp_path, [gate], max_speakers=1)
        run = asyncio.create_task(controller.run("review implementation"))
        await controller.wait_until_responding(1)

        with pytest.raises(ValueError, match="evidence"):
            await controller.interrupt(
                "agent-1",
                priority="urgent",
                reason="disagree",
                evidence=None,
            )

        assert await controller.interrupt(
            "agent-1",
            priority="urgent",
            reason="new failing test",
            evidence="tests/test_parser.py::test_empty",
        )
        await run
        kinds = [event.kind for event in controller.room.store.replay("run-1")]
        assert "message.interrupted" in kinds
        assert kinds[-1] == "run.completed"

    asyncio.run(scenario())


def test_run_completion_waits_for_interrupt_receipt(tmp_path: Path) -> None:
    class DelayedInterruptAdapter(FakeAdapter):
        async def interrupt(self, reason: str) -> bool:
            interrupted = await super().interrupt(reason)
            await asyncio.sleep(0.05)
            return interrupted

    async def scenario() -> None:
        gate = asyncio.Event()
        participant = _participant("agent-1")
        adapter = DelayedInterruptAdapter(
            participant,
            scripts=(("unfinished",),),
            pause=gate,
        )
        controller = RunController(
            run_id="run-ordered-interrupt",
            adapters={participant.participant_id: adapter},
            room=CollaborationRoom(EventStore(tmp_path / "ordered-interrupt.db")),
            max_simultaneous_speakers=1,
        )
        run = asyncio.create_task(controller.run("review implementation"))
        await controller.wait_until_responding(1)

        assert await controller.interrupt(
            "agent-1",
            priority="urgent",
            reason="new failing test",
            evidence="tests/test_parser.py::test_empty",
        )
        await run

        kinds = [event.kind for event in controller.room.store.replay("run-ordered-interrupt")]
        assert kinds[-2:] == ["interrupt.applied", "run.completed"]

    asyncio.run(scenario())


def _child_controller(
    tmp_path: Path,
    *,
    max_participants: int,
    max_depth: int = 2,
    token_budget: int = 2000,
) -> RunController:
    parent = _participant("builder")
    parent_adapter = FakeAdapter(parent, scripts=(("parent",),))

    def child_factory(participant: Participant, request: ChildRequest) -> FakeAdapter:
        return FakeAdapter(participant, scripts=((request.objective,),))

    return RunController(
        run_id="run-child",
        adapters={"builder": parent_adapter},
        room=CollaborationRoom(EventStore(tmp_path / "children.db")),
        max_simultaneous_speakers=1,
        capacity=CapacityPolicy(
            max_participants=max_participants,
            max_dynamic_children=max(0, max_participants - 1),
            max_children_per_parent=2,
            max_spawn_depth=max_depth,
            max_simultaneous_speakers=1,
        ),
        total_token_budget=token_budget,
        child_adapter_factory=child_factory,
    )


def test_child_joins_with_independent_context_and_lineage(tmp_path: Path) -> None:
    async def scenario() -> None:
        controller = _child_controller(tmp_path, max_participants=3)

        child = await controller.spawn_child(
            parent_id="builder",
            role="test-specialist",
            objective="write boundary tests",
            context=("requirement: reject empty input",),
            token_budget=1000,
        )

        assert child.parent_id == "builder"
        assert child.participant_id == "builder/test-specialist-1"
        assert controller.context_for(child.participant_id) == ("requirement: reject empty input",)
        await controller.wait_for_children()
        child_events = [
            event
            for event in controller.room.store.replay("run-child")
            if event.actor == child.participant_id
        ]
        assert [event.kind for event in child_events] == [
            "message.started",
            "message.delta",
            "message.completed",
        ]

    asyncio.run(scenario())


def test_child_cannot_exceed_participant_capacity(tmp_path: Path) -> None:
    async def scenario() -> None:
        controller = _child_controller(tmp_path, max_participants=1)

        with pytest.raises(RuntimeError, match="participant capacity"):
            await controller.spawn_child("builder", "reviewer", "review", (), 100)

    asyncio.run(scenario())


def test_child_budget_is_reserved_and_cannot_be_reused(tmp_path: Path) -> None:
    async def scenario() -> None:
        controller = _child_controller(tmp_path, max_participants=3, token_budget=1000)
        await controller.spawn_child("builder", "reviewer", "review", (), 800)

        with pytest.raises(RuntimeError, match="token budget"):
            await controller.spawn_child("builder", "tester", "test", (), 300)

    asyncio.run(scenario())


def test_child_adapter_failure_persists_degraded_lineage(tmp_path: Path) -> None:
    async def scenario() -> None:
        parent = _participant("builder")

        def failing_factory(participant: Participant, request: ChildRequest) -> FakeAdapter:
            del request
            return FakeAdapter(participant, scripts=())

        controller = RunController(
            run_id="run-degraded-child",
            adapters={"builder": FakeAdapter(parent, scripts=(("parent",),))},
            room=CollaborationRoom(EventStore(tmp_path / "degraded-child.db")),
            max_simultaneous_speakers=1,
            capacity=CapacityPolicy(2, 1, 1, 1, 1),
            total_token_budget=1000,
            child_adapter_factory=failing_factory,
        )

        child = await controller.spawn_child(
            "builder", "tester", "exercise failure", ("selected",), 200
        )
        await controller.wait_for_children()

        events = controller.room.store.replay("run-degraded-child")
        degraded = [event for event in events if event.kind == "participant.degraded"]
        assert child.parent_id == "builder"
        assert controller.context_for(child.participant_id) == ("selected",)
        assert degraded[0].payload["participant_id"] == child.participant_id

    asyncio.run(scenario())


def test_resume_budget_does_not_restore_consumed_child_allocation(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        parent = _participant("builder")

        def child_factory(participant: Participant, request: ChildRequest) -> FakeAdapter:
            return FakeAdapter(participant, scripts=((request.objective,),))

        controller = RunController(
            run_id="run-reserved-budget",
            adapters={"builder": FakeAdapter(parent, scripts=(("parent",),))},
            room=CollaborationRoom(EventStore(tmp_path / "reserved-budget.db")),
            max_simultaneous_speakers=1,
            capacity=CapacityPolicy(2, 1, 1, 1, 1),
            total_token_budget=1000,
            consumed_token_budget=900,
            child_adapter_factory=child_factory,
        )

        with pytest.raises(RuntimeError, match="token budget"):
            await controller.spawn_child("builder", "tester", "test", (), 200)

    asyncio.run(scenario())


def test_controller_rejects_inconsistent_roster_and_budget_configuration(
    tmp_path: Path,
) -> None:
    participant = _participant("builder")
    adapter = FakeAdapter(participant, scripts=(("response",),))
    room = CollaborationRoom(EventStore(tmp_path / "validation.db"))

    with pytest.raises(ValueError, match="speaker limit"):
        RunController(run_id="run-1", adapters={}, room=room, max_simultaneous_speakers=0)
    with pytest.raises(ValueError, match="adapter keys"):
        RunController(
            run_id="run-1",
            adapters={"wrong": adapter},
            room=room,
            max_simultaneous_speakers=1,
        )
    with pytest.raises(ValueError, match="roster participant"):
        RunController(
            run_id="run-1",
            adapters={"builder": adapter},
            participants={},
            room=room,
            max_simultaneous_speakers=1,
        )
    with pytest.raises(ValueError, match="match the roster"):
        RunController(
            run_id="run-1",
            adapters={"builder": adapter},
            participants={"builder": _participant("different")},
            room=room,
            max_simultaneous_speakers=1,
        )
    with pytest.raises(ValueError, match="participant capacity"):
        RunController(
            run_id="run-1",
            adapters={"builder": adapter},
            room=room,
            max_simultaneous_speakers=1,
            capacity=CapacityPolicy(1, 0, 0, 0, 1),
            participants={"builder": participant, "other": _participant("other")},
        )
    with pytest.raises(ValueError, match="total token budget"):
        RunController(
            run_id="run-1",
            adapters={"builder": adapter},
            room=room,
            max_simultaneous_speakers=1,
            total_token_budget=0,
        )
    with pytest.raises(ValueError, match="consumed token budget"):
        RunController(
            run_id="run-1",
            adapters={"builder": adapter},
            room=room,
            max_simultaneous_speakers=1,
            total_token_budget=100,
            consumed_token_budget=101,
        )
    with pytest.raises(ValueError, match="unknown participant"):
        RunController(
            run_id="run-1",
            adapters={"builder": adapter},
            room=room,
            max_simultaneous_speakers=1,
            contexts={"missing": ()},
        )


def test_child_rejection_covers_each_governance_limit(tmp_path: Path) -> None:
    async def scenario() -> None:
        parent = _participant("builder")
        adapter = FakeAdapter(parent, scripts=(("parent",),))

        def factory(participant: Participant, request: ChildRequest) -> FakeAdapter:
            return FakeAdapter(participant, scripts=((request.objective,),))

        async def rejected(
            run_id: str,
            policy: CapacityPolicy,
            expected: str,
            *,
            parent_id: str = "builder",
            use_factory: bool = True,
        ) -> None:
            controller = RunController(
                run_id=run_id,
                adapters={"builder": adapter},
                room=CollaborationRoom(EventStore(tmp_path / f"{run_id}.db")),
                max_simultaneous_speakers=1,
                capacity=policy,
                total_token_budget=1000,
                child_adapter_factory=factory if use_factory else None,
            )
            with pytest.raises(RuntimeError, match=expected):
                await controller.spawn_child(parent_id, "tester", "test", (), 100)

        await rejected(
            "unknown-parent", CapacityPolicy(2, 1, 1, 1, 1), "unknown parent", parent_id="missing"
        )
        await rejected("dynamic-cap", CapacityPolicy(2, 0, 1, 1, 1), "dynamic child")
        await rejected("parent-cap", CapacityPolicy(2, 1, 0, 1, 1), "children-per-parent")
        await rejected("depth-cap", CapacityPolicy(2, 1, 1, 0, 1), "spawn depth")
        await rejected(
            "no-factory",
            CapacityPolicy(2, 1, 1, 1, 1),
            "factory",
            use_factory=False,
        )

    asyncio.run(scenario())


def test_child_factory_construction_failure_persists_degraded_event(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        parent = _participant("builder")

        def failing_factory(participant: Participant, request: ChildRequest) -> FakeAdapter:
            del participant, request
            raise RuntimeError("factory unavailable")

        controller = RunController(
            run_id="run-factory-failure",
            adapters={"builder": FakeAdapter(parent, scripts=(("parent",),))},
            room=CollaborationRoom(EventStore(tmp_path / "factory-failure.db")),
            max_simultaneous_speakers=1,
            capacity=CapacityPolicy(2, 1, 1, 1, 1),
            total_token_budget=1000,
            child_adapter_factory=failing_factory,
        )

        child = await controller.spawn_child("builder", "tester", "test", (), 100)

        degraded = [
            event
            for event in controller.room.store.replay("run-factory-failure")
            if event.kind == "participant.degraded"
        ]
        assert degraded[0].payload["participant_id"] == child.participant_id

    asyncio.run(scenario())

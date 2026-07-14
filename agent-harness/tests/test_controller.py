import asyncio
from pathlib import Path

import pytest

from agent_harness.adapters.fake import FakeAdapter
from agent_harness.controller import RunController
from agent_harness.models import Participant
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

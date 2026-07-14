import asyncio

from agent_harness.adapters.fake import FakeAdapter
from agent_harness.models import Participant


def _participant() -> Participant:
    return Participant("builder", "fake", "fake-v1", ("implementation",), 4096, None)


def test_fake_adapter_streams_scripted_chunks() -> None:
    async def scenario() -> None:
        adapter = FakeAdapter(_participant(), scripts=(("hello ", "room"),))

        emissions = [item async for item in adapter.respond("goal")]

        assert [item.kind for item in emissions] == [
            "message.started",
            "message.delta",
            "message.delta",
            "message.completed",
        ]
        assert [item.content for item in emissions[1:3]] == ["hello ", "room"]

    asyncio.run(scenario())


def test_fake_adapter_preserves_interrupted_partial_response() -> None:
    async def scenario() -> None:
        pause = asyncio.Event()
        adapter = FakeAdapter(_participant(), scripts=(("discarded",),), pause=pause)

        async def collect() -> list[str]:
            return [item.kind async for item in adapter.respond("goal")]

        response = asyncio.create_task(collect())
        await asyncio.sleep(0)
        assert await adapter.interrupt("new failing test") is True

        assert await response == ["message.started", "message.interrupted"]

    asyncio.run(scenario())

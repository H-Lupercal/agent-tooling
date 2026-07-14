"""Deterministic offline participant used by tests and demos."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterator, Iterable

from agent_harness.adapters.base import Emission
from agent_harness.models import Participant


class FakeAdapter:
    def __init__(
        self,
        participant: Participant,
        scripts: Iterable[tuple[str, ...]],
        *,
        pause: asyncio.Event | None = None,
    ) -> None:
        self.participant = participant
        self._scripts = deque(scripts)
        self._pause = pause
        self._active = False
        self._interrupted = False

    async def respond(self, prompt: str) -> AsyncIterator[Emission]:
        del prompt
        if not self._scripts:
            raise RuntimeError("fake adapter script exhausted")
        script = self._scripts.popleft()
        self._active = True
        self._interrupted = False
        try:
            yield Emission("message.started", "")
            if self._pause is not None:
                await self._pause.wait()
            if self._interrupted:
                yield Emission("message.interrupted", "")
                return
            for chunk in script:
                if self._interrupted:
                    yield Emission("message.interrupted", "")
                    return
                yield Emission("message.delta", chunk)
            if self._interrupted:
                yield Emission("message.interrupted", "")
                return
            yield Emission("message.completed", "")
        finally:
            self._active = False

    async def interrupt(self, reason: str) -> bool:
        del reason
        if not self._active:
            return False
        self._interrupted = True
        if self._pause is not None:
            self._pause.set()
        return True

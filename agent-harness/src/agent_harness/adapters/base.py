"""Common protocol implemented by every participant adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Protocol

from agent_harness.models import Participant


@dataclass(frozen=True)
class Emission:
    kind: str
    content: str


class ParticipantAdapter(Protocol):
    participant: Participant

    def respond(self, prompt: str) -> AsyncIterator[Emission]: ...

    async def interrupt(self, reason: str) -> bool: ...

"""Participant adapter contracts and built-in implementations."""

from agent_harness.adapters.base import Emission, ParticipantAdapter
from agent_harness.adapters.fake import FakeAdapter

__all__ = ["Emission", "FakeAdapter", "ParticipantAdapter"]

from __future__ import annotations

from typing import ClassVar


class ToolbeltError(Exception):
    """Base class for expected failures with a stable process exit code."""

    exit_code: ClassVar[int] = 10


class UsageError(ToolbeltError):
    exit_code = 2


class ValidationError(ToolbeltError):
    exit_code = 3


ValidationToolbeltError = ValidationError


class StalePlanError(ToolbeltError):
    exit_code = 4


class DeclinedError(ToolbeltError):
    exit_code = 5


class ApplyError(ToolbeltError):
    exit_code = 6


class RollbackError(ToolbeltError):
    exit_code = 7


class VerificationError(ToolbeltError):
    exit_code = 8


class DriftError(ToolbeltError):
    exit_code = 9


class InternalError(ToolbeltError):
    exit_code = 10


__all__ = [
    "ApplyError",
    "DeclinedError",
    "DriftError",
    "InternalError",
    "RollbackError",
    "StalePlanError",
    "ToolbeltError",
    "UsageError",
    "ValidationError",
    "ValidationToolbeltError",
    "VerificationError",
]
